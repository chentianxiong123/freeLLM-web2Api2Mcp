"""Chat 编排层 — 翻译器

职责：把 OpenAI 格式请求翻译给 DeepSeek，把 DeepSeek 响应翻译回 OpenAI 格式。

两个核心功能：
  1. build_ds_input(body) → ChatRequest
     从 CC 的 OpenAI 消息中提取要发给 DS 的内容

  2. collect_response(events, ...) → dict
     把 Provider 的 Event 流组装成 OpenAI Chat Completions 响应
"""

import json
import time
import uuid
from dataclasses import dataclass

from providers.base import Event


# ── 1. body → 发给 DS 的消息 ───────────────────────────


@dataclass
class ChatRequest:
    """描述一次"发到 Provider 的请求"。"""
    user_content: str            # 要发到 Provider 的 user 消息
    is_react_continuation: bool  # True = body 含 tool role，是 react 续接
    tool_call_ids: list[str]     # body 里的 tool_call_id（用于诊断/续接）


def build_ds_input(body: dict) -> ChatRequest:
    """从 OpenAI 风格 body 构造 ChatRequest。

    判定规则（只看末尾，不看历史）：
      - 最后一条 role=tool → react 续接 → 发这条 tool 的内容
      - 最后一条 role=user → 新的人话 → 发这条 user 的内容
    """
    msgs = body.get("messages", []) or []
    last = msgs[-1] if msgs else {}
    last_role = last.get("role", "?")

    print(f"[build_ds_input] msgs count={len(msgs)}, last_role={last_role}")

    # react 续接：末尾是 tool → 发工具结果
    if last_role == "tool":
        tcid = last.get("tool_call_id", "")
        c = last.get("content", "")
        if isinstance(c, str):
            content = c
        elif isinstance(c, list):
            parts = []
            for b in c:
                if isinstance(b, dict):
                    if b.get("type") == "text":
                        parts.append(b.get("text", ""))
                    else:
                        parts.append(json.dumps(b, ensure_ascii=False))
            content = "\n".join(parts)
        else:
            content = str(c)
        print(f"[build_ds_input] → REACT continuation, tool_call_id={tcid}")
        return ChatRequest(user_content=content, is_react_continuation=True, tool_call_ids=[tcid])

    # 人话：末尾是 user → 发用户内容
    if last_role == "user":
        c = last.get("content", "")
        if isinstance(c, str):
            content = c
        elif isinstance(c, list):
            parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
            content = "\n".join(parts)
        else:
            content = str(c)
        print(f"[build_ds_input] → USER message, len={len(content)}")
        return ChatRequest(user_content=content, is_react_continuation=False, tool_call_ids=[])

    # 兜底：末尾是 system/assistant → 异常，发最后一条 user
    for m in reversed(msgs):
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, str):
                content = c
            elif isinstance(c, list):
                parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
                content = "\n".join(parts)
            else:
                content = str(c)
            print(f"[build_ds_input] → FALLBACK to last user, len={len(content)}")
            return ChatRequest(user_content=content, is_react_continuation=False, tool_call_ids=[])
    return ChatRequest(user_content="", is_react_continuation=False, tool_call_ids=[])


# ── 2. 拦截：housekeeping / rules ─────────────────────────


def check_housekeeping(body: dict) -> bool:
    """Claude Code 后台 housekeeping？直接挡。"""
    try:
        import gateway
        result = gateway.is_claude_housekeeping_request(body)
        print(f"[check_housekeeping] result={result}")
        return result
    except Exception as e:
        print(f"[check_housekeeping] EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_rules(body: dict) -> tuple[bool, dict | None]:
    """可配置规则引擎拦截。返回 (是否拦截, 命中的规则)。"""
    try:
        import gateway
        import rules
        clean_prompt = gateway.extract_clean_user_prompt(body)
        blocked, hit = rules.is_blocked(body, clean_prompt)
        if blocked:
            print(f"[check_rules] BLOCKED by rule: {hit.get('name', '?')}")
        return blocked, hit
    except Exception as e:
        print(f"[check_rules] ERROR: {e}")
        return False, None


def make_skip_response(model: str, request_id: str, reason: str = "blocked") -> dict:
    """生成"跳过"响应（housekeeping / rules 命中时返回）。"""
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": ""},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


# ── 3. 工具块解析 ──────────────────────────────────────


def _detect_tool_blocks(text: str) -> tuple[str, list[dict]]:
    """从文本里切出工具块。返回 (剩余文本, 工具调用列表[{name, arguments}])。"""
    try:
        from tool_format import parse_tool_blocks
        return parse_tool_blocks(text, None)
    except Exception:
        return text, []


def _filter_response_content(content: str) -> tuple[str, list[dict]]:
    """过滤 DS 响应内容（委托 rules.filter_response）。"""
    try:
        from rules import filter_response
        return filter_response(content)
    except Exception:
        return content, []


# ── 4. Provider Event → OpenAI 响应 ─────────────────────


def _build_openai_tool_call(tc: dict) -> dict:
    """把 {name, arguments} 转换成 OpenAI tool_calls 格式。"""
    from tool_format import build_openai_tool_call
    return build_openai_tool_call(
        f"call_{uuid.uuid4().hex[:24]}",
        tc["name"],
        tc["arguments"],
    )


async def collect_response(
    events,
    *,
    request_id: str,
    model: str,
    tools_schema: list[dict] | None = None,
) -> dict:
    """收集所有事件，返回完整的 OpenAI 响应 dict。"""
    thinking_parts: list[str] = []
    content_parts: list[str] = []
    tool_calls: list[dict] = []
    total_tokens: int | None = None
    error_occurred = False
    error_msg = ""

    async for ev in events:
        if ev.type == "thinking":
            if isinstance(ev.val, str) and ev.val:
                thinking_parts.append(ev.val)
        elif ev.type == "content":
            if isinstance(ev.val, str):
                content_parts.append(ev.val)
        elif ev.type == "tool_call":
            # Provider 直接给结构化 tool_call → 直接收集
            if isinstance(ev.val, dict):
                tc_name = ev.val.get("name", "?")
                tc_args = ev.val.get("arguments", {})
                tool_calls.append({"name": tc_name, "arguments": tc_args})
        elif ev.type == "token_usage":
            if isinstance(ev.val, (int, float)) and ev.val:
                total_tokens = int(ev.val)
        elif ev.type == "error":
            error_occurred = True
            error_msg = str(ev.val)
        elif ev.type == "done":
            break

    # 错误
    if error_occurred:
        return {
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": f"[错误] {error_msg}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    # 如果 provider 没给结构化 tool_calls（比如文本模式），从 content 解析
    if not tool_calls:
        full_content = "".join(content_parts)
        remaining_text, parsed_calls = _detect_tool_blocks(full_content)
    else:
        remaining_text = "".join(content_parts)
        parsed_calls = tool_calls

    # 构建 message
    message = {"role": "assistant"}
    if parsed_calls:
        message["content"] = remaining_text or None
        message["tool_calls"] = [_build_openai_tool_call(tc) for tc in parsed_calls]
        finish_reason = "tool_calls"
    else:
        message["content"] = remaining_text or None
        finish_reason = "stop"

    # thinking
    thinking_text = "\n".join(thinking_parts) if thinking_parts else None

    # usage
    full_content = "".join(content_parts)
    completion_est = max(1, len(full_content) // 4) if full_content else 0
    prompt_est = max(0, total_tokens - completion_est) if total_tokens else 0
    usage = {
        "prompt_tokens": prompt_est,
        "completion_tokens": completion_est,
        "total_tokens": total_tokens or 0,
    }

    result = {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage,
    }

    if thinking_text:
        result["thinking"] = thinking_text

    return result

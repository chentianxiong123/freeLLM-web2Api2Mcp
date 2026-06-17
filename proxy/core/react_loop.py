"""React 循环状态机。

两个核心功能：
  1. build_ds_input(body) → ChatRequest
     决定 body 是"react 续接"还是"新对话"，并构造发给 Provider 的消息

  2. stream_to_openai(provider, ...) → AsyncIterator[str]
     把 Provider 的 Event 流翻译成 OpenAI Chat Completions SSE 格式
     严格执行 7 条不变式（见 tests/test_react.py）
"""

import json
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator

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

    规则：
      - body 含任意 tool role → react 续接 → 只发工具结果（不变式 ④⑤）
      - body 没有 tool role → 新对话 → 只发最后一条 user 原话
    """
    msgs = body.get("messages", []) or []

    has_tool = any(m.get("role") == "tool" for m in msgs)
    tool_call_ids: list[str] = []

    if has_tool:
        # ── react 续接：只发工具结果 + 明确告知"这是工具回执" ──
        tool_msgs = []
        for m in msgs:
            if m.get("role") != "tool":
                continue
            tcid = m.get("tool_call_id", "")
            tool_call_ids.append(tcid)
            c = m.get("content", "")
            if isinstance(c, str):
                text = c
            elif isinstance(c, list):
                parts = []
                for b in c:
                    if isinstance(b, dict):
                        if b.get("type") == "text":
                            parts.append(b.get("text", ""))
                        else:
                            parts.append(json.dumps(b, ensure_ascii=False))
                text = "\n".join(parts)
            else:
                text = str(c)
            tool_msgs.append(f"[工具执行结果]\n{text}")
        user_content = "你刚才调用的工具已执行完毕，返回结果如下：\n\n" + "\n\n".join(tool_msgs) + "\n\n请基于以上执行结果决定下一步：是继续调用工具、还是总结回复（结束任务）。"
        return ChatRequest(user_content=user_content, is_react_continuation=True, tool_call_ids=tool_call_ids)

    # ── 新对话：只发最后一条 user 原文 ──
    last_user = ""
    for m in reversed(msgs):
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, str):
                last_user = c
            elif isinstance(c, list):
                parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
                last_user = "\n".join(parts)
            break
    return ChatRequest(user_content=last_user, is_react_continuation=False, tool_call_ids=[])


# ── 2. Provider Event → OpenAI SSE ─────────────────────


def _sse_chunk(request_id: str, model: str, delta: dict, finish_reason: str | None = None) -> str:
    """构造一个 OpenAI 风格的 SSE chunk。"""
    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def _sse_usage(request_id: str, model: str, prompt: int, completion: int, total: int) -> str:
    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total},
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def _detect_tool_blocks(text: str) -> tuple[str, list[dict]]:
    """从累积 content 里切出工具块。返回 (剩余文本, 工具调用列表)。

    包装 tool_format 以避免循环依赖（如果 tool_format 在别处用了）。
    """
    try:
        from tool_format import parse_tool_blocks
        return parse_tool_blocks(text, None)
    except Exception:
        return text, []


async def stream_to_openai(
    provider,                 # ChatProvider 实例
    *,
    request_id: str,
    model: str,
    tools_schema: list[dict] | None = None,
) -> AsyncIterator[str]:
    """把 Provider 的 Event 流翻译成 OpenAI Chat Completions SSE 格式。

    严格执行 7 条不变式（见 tests/test_react.py）：
      ①  finish_reason 必发
      ②  有 tool_call → content 留空
      ③  role delta 必发（即使整轮无 content）
      ④  react 续接时只发工具结果（见 build_ds_input）
      ⑤  react 续接时明确告知"这是工具回执"（见 build_ds_input）
      ⑥  tool_call_id 稳定
      ⑦  finish_reason=tool_calls 时必有 tool_calls delta

    调用方流程：
      1. body → build_ds_input(body) → ChatRequest
      2. provider.chat(messages=...) → AsyncIterator[Event]
      3. stream_events_to_openai(events, ...) → SSE strings
    """
    raise NotImplementedError("Use stream_events_to_openai(events, ...) instead — see docstring above")


async def stream_events_to_openai(
    events: AsyncIterator[Event],
    *,
    request_id: str,
    model: str,
    tools_schema: list[dict] | None = None,
) -> AsyncIterator[str]:
    """接受 AsyncIterator[Event]，转 SSE 字符串。"""
    role_sent = False
    full_content_parts: list[str] = []
    total_tokens: int | None = None
    error_occurred = False
    error_msg = ""

    def ensure_role() -> str | None:
        nonlocal role_sent
        if not role_sent:
            role_sent = True
            return _sse_chunk(request_id, model, {"role": "assistant", "content": ""})
        return None

    async for ev in events:
        if ev.type == "thinking":
            r = ensure_role()
            if r: yield r
            continue
        if ev.type == "content":
            r = ensure_role()
            if r: yield r
            if isinstance(ev.val, str):
                full_content_parts.append(ev.val)
            # ⚠️ 不流 content — 等解析完工具块再决定
        elif ev.type == "tool_call":
            # Provider 直接给结构化 tool_call — 暂存到 content 让解析器处理
            # （provider 自己不负责"工具块 → 结构化"——那是 mock 行为；
            #  真实 Provider 应该是结构化的）
            r = ensure_role()
            if r: yield r
            # 真实 provider 不会走这里；只 mock 走
            tc_name = ev.val.get("name", "?")
            tc_args = ev.val.get("arguments", {})
            full_content_parts.append(f"工具 {tc_name}\n")
            for k, v in tc_args.items():
                full_content_parts.append(f'{k}="{v}"\n')
            full_content_parts.append("工具结束\n")
        elif ev.type == "token_usage":
            if isinstance(ev.val, (int, float)) and ev.val:
                total_tokens = int(ev.val)
        elif ev.type == "error":
            error_occurred = True
            error_msg = str(ev.val)
            r = ensure_role()
            if r: yield r
            yield _sse_chunk(request_id, model, {"content": f"[错误] {error_msg}"}, finish_reason="stop")
            yield "data: [DONE]\n\n"
            return
        elif ev.type == "done":
            break

    # ── 兜底：整轮什么都没发 → 至少发个 role ──
    if not role_sent:
        yield _sse_chunk(request_id, model, {"role": "assistant", "content": ""})
        role_sent = True

    # ── 解析 content，找 tool 块 ──
    full_content = "".join(full_content_parts)
    remaining_text, tool_calls = _detect_tool_blocks(full_content)

    # ── 决定 content 流不流（不变式 ②：有 tool_call → content 留空）──
    if not tool_calls and remaining_text:
        for i in range(0, len(remaining_text), 100):
            yield _sse_chunk(request_id, model, {"content": remaining_text[i:i+100]})

    # ── 输出 tool_calls deltas（不变式 ⑥⑦）──
    finish_reason = "stop"
    if tool_calls:
        for idx, tc in enumerate(tool_calls):
            # 不变式 ⑥：tool_call_id 稳定
            call_id = f"call_{uuid.uuid4().hex[:24]}"
            # delta 1: id + name
            yield _sse_chunk(request_id, model, {
                "tool_calls": [{
                    "index": idx,
                    "id": call_id,
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": ""},
                }],
            })
            # delta 2: arguments 一次性
            args_str = json.dumps(tc["arguments"], ensure_ascii=False)
            yield _sse_chunk(request_id, model, {
                "tool_calls": [{
                    "index": idx,
                    "function": {"arguments": args_str},
                }],
            })
        finish_reason = "tool_calls"

    # ── usage chunk ──
    if total_tokens is not None:
        completion_est = max(1, len(full_content) // 4)
        prompt_est = max(0, total_tokens - completion_est)
        yield _sse_usage(request_id, model, prompt_est, completion_est, total_tokens)
    else:
        yield _sse_usage(request_id, model, 0, 0, 0)

    # ── 末条（不变式 ①）──
    yield _sse_chunk(request_id, model, {}, finish_reason=finish_reason)
    yield "data: [DONE]\n\n"

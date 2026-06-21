"""Chat 编排层 — 翻译器

职责：把 Provider 的 Event 流组装成 OpenAI Chat Completions 响应。

请求解析（build_ds_input）已移至 request_parser.py。
"""

import time
import uuid

from typing import AsyncIterator

from providers.base import Event


# ── 1. 跳过响应 ──────────────────────────────────────


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
    events: AsyncIterator[Event],
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

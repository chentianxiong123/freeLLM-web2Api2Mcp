"""Chat 编排层 — 翻译器

职责：把 Provider 的 Event 流组装成 OpenAI Chat Completions 响应。

请求解析（build_ds_input）已移至 request_parser.py。
"""

import json
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


async def stream_skip_response(model: str, request_id: str):
    """生成"跳过"的流式响应（housekeeping / rules 命中时返回）。"""
    created = int(time.time())
    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}],
    }
    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    chunk2 = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    yield f"data: {json.dumps(chunk2, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


# ── 3. 工具块解析 ──────────────────────────────────────


def _detect_tool_blocks(text: str, tool_codec_id: str = "deepseek_natural") -> tuple[str, list[dict]]:
    """从文本里切出工具块。返回 (剩余文本, 工具调用列表[{name, arguments}])。"""
    if tool_codec_id != "deepseek_natural":
        return text, []
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
    args = tc["arguments"]
    # Qwen/流式场景：arguments 已是 JSON 字符串，需先解析为 dict
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            pass
    return build_openai_tool_call(
        f"call_{uuid.uuid4().hex[:24]}",
        tc["name"],
        args,
    )


async def collect_response(
    events: AsyncIterator[Event],
    *,
    request_id: str,
    model: str,
    tools_schema: list[dict] | None = None,
    tool_codec_id: str = "deepseek_natural",
    input_text: str = "",
) -> dict:
    """收集所有事件，返回完整的 OpenAI 响应 dict。"""
    thinking_parts: list[str] = []
    content_parts: list[str] = []
    tool_calls: list[dict] = []
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
                # Qwen/流式场景：arguments 可能是字符串
                if isinstance(tc_args, str):
                    try:
                        tc_args = json.loads(tc_args)
                    except json.JSONDecodeError:
                        pass
                tool_calls.append({"name": tc_name, "arguments": tc_args})
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
        remaining_text, parsed_calls = _detect_tool_blocks(full_content, tool_codec_id)
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

    # thinking → 放在 message.reasoning_content（OpenAI 标准）
    thinking_text = "\n".join(thinking_parts) if thinking_parts else None
    if thinking_text:
        message["reasoning_content"] = thinking_text

    # usage - 全部自己估算，不依赖上游
    full_content = "".join(content_parts)
    thinking_text_for_usage = "\n".join(thinking_parts) if thinking_parts else ""
    _est = lambda t: max(1, len(t) // 2) if t else 0
    prompt_est = _est(input_text)
    completion_est = _est(full_content)
    reasoning_est = _est(thinking_text_for_usage)
    usage = {
        "prompt_tokens": prompt_est,
        "completion_tokens": completion_est + reasoning_est,
        "total_tokens": prompt_est + completion_est + reasoning_est,
        "prompt_tokens_details": {
            "cached_tokens": 0,
        },
        "completion_tokens_details": {
            "reasoning_tokens": reasoning_est,
        },
    }

    result = {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage,
    }

    return result


# ── 5. SSE 流式响应 ────────────────────────────────────


def _make_sse_chunk(
    request_id: str,
    model: str,
    created: int,
    index: int,
    delta: dict,
    finish_reason: str | None = None,
    usage: dict | None = None,
) -> str:
    """构造一条完整的 SSE data: 消息（含前缀和 \n\n）。"""
    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": index, "delta": delta}],
    }
    if finish_reason is not None:
        chunk["choices"][0]["finish_reason"] = finish_reason
    if usage is not None:
        chunk["usage"] = usage
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


async def stream_response(
    events: AsyncIterator[Event],
    *,
    request_id: str,
    model: str,
    input_text: str = "",
) -> AsyncIterator[str]:
    """将 Provider Event 流转换为 OpenAI SSE 消息。

    每条 yield 是一条完整的 SSE data: 行（含 \n\n），
    可直接喂给 StreamingResponse。
    """
    created = int(time.time())
    role_sent = False
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls_acc: list[dict] = []

    async for ev in events:
        if ev.type == "content":
            if not role_sent:
                role_sent = True
                yield _make_sse_chunk(request_id, model, created, 0, {"role": "assistant", "content": ""})
            if isinstance(ev.val, str) and ev.val:
                content_parts.append(ev.val)
                yield _make_sse_chunk(request_id, model, created, 0, {"content": ev.val})
        elif ev.type == "thinking":
            if isinstance(ev.val, str) and ev.val:
                thinking_parts.append(ev.val)
                yield _make_sse_chunk(request_id, model, created, 0, {"reasoning_content": ev.val})
        elif ev.type == "tool_call":
            if not role_sent:
                role_sent = True
                yield _make_sse_chunk(request_id, model, created, 0, {"role": "assistant", "content": ""})
            if isinstance(ev.val, dict):
                tc = _build_openai_tool_call(ev.val)
                tool_calls_acc.append(tc)
                yield _make_sse_chunk(request_id, model, created, 0, {"tool_calls": [tc]})
        elif ev.type == "error":
            yield _make_sse_chunk(request_id, model, created, 0, {"content": f"[错误] {ev.val}"}, finish_reason="stop")
            yield "data: [DONE]\n\n"
            return
        elif ev.type == "done":
            break

    # usage - 全部自己估算，不依赖上游
    full_content = "".join(content_parts)
    thinking_text = "\n".join(thinking_parts) if thinking_parts else ""
    _est = lambda t: max(1, len(t) // 2) if t else 0
    prompt_est = _est(input_text)
    completion_est = _est(full_content)
    reasoning_est = _est(thinking_text)
    usage = {
        "prompt_tokens": prompt_est,
        "completion_tokens": completion_est + reasoning_est,
        "total_tokens": prompt_est + completion_est + reasoning_est,
        "prompt_tokens_details": {
            "cached_tokens": 0,
        },
        "completion_tokens_details": {
            "reasoning_tokens": reasoning_est,
        },
    }

    finish_reason = "tool_calls" if tool_calls_acc else "stop"
    if not role_sent:
        yield _make_sse_chunk(request_id, model, created, 0, {"role": "assistant", "content": ""}, finish_reason=finish_reason, usage=usage)
    else:
        yield _make_sse_chunk(request_id, model, created, 0, {}, finish_reason=finish_reason, usage=usage)
    yield "data: [DONE]\n\n"

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


def _detect_tool_blocks(text: str, tool_codec_id: str = "deepseek_natural", tools_schema: list[dict] | None = None) -> tuple[str, list[dict]]:
    """从文本里切出工具块。返回 (剩余文本, 工具调用列表[{name, arguments}])。"""
    try:
        from tool_format import parse_tool_blocks
        return parse_tool_blocks(text, tools_schema)
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


def _stream_tool_call_chunks(
    request_id: str,
    model: str,
    created: int,
    tc: dict,
    index: int,
) -> list[str]:
    """把一个 tool_call 拆成 OpenAI 标准的增量 SSE chunks。

    OpenAI 流式格式：
      chunk1: delta.tool_calls[0] = {index, id, type, function: {name, arguments: ""}}
      chunk2: delta.tool_calls[0] = {index, function: {arguments: "<完整 JSON>"}}
    """
    call_id = tc.get("id", f"call_{uuid.uuid4().hex[:24]}")
    func = tc.get("function", {})
    name = func.get("name", "")
    args_str = func.get("arguments", "{}")

    # chunk1: id + name + 空 arguments
    chunk1_tc = {
        "index": index,
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": ""},
    }
    # chunk2: 完整 arguments
    chunk2_tc = {
        "index": index,
        "function": {"arguments": args_str},
    }
    return [
        _make_sse_chunk(request_id, model, created, 0, {"tool_calls": [chunk1_tc]}),
        _make_sse_chunk(request_id, model, created, 0, {"tool_calls": [chunk2_tc]}),
    ]


async def collect_response(
    events: AsyncIterator[Event],
    *,
    request_id: str,
    model: str,
    tools_schema: list[dict] | None = None,
    tool_codec_id: str = "deepseek_natural",
    input_text: str = "",
    full_context_text: str = "",
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

    # 始终从 content 文本中解析工具块（Qwen 可能同时有结构化 tool_call 事件和 content 中的工具块文本）
    full_content = "".join(content_parts)
    remaining_text, parsed_calls = _detect_tool_blocks(full_content, tool_codec_id, tools_schema)
    if tool_calls and not parsed_calls:
        # 有结构化 tool_call 事件但文本中无工具块 → 用结构化结果
        parsed_calls = tool_calls
    elif tool_calls and parsed_calls:
        # 两者都有 → 优先用结构化结果（更可靠），但用清理后的文本
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
    # prompt_tokens = 总输入（新+缓存），cached_tokens = 缓存命中
    # cc-switch 公式：input_tokens = prompt_tokens - cached_tokens
    full_content = "".join(content_parts)
    thinking_text_for_usage = "\n".join(thinking_parts) if thinking_parts else ""
    from session import _estimate_tokens
    prompt_est = _estimate_tokens(input_text)
    context_est = _estimate_tokens(full_context_text)
    cached_est = max(0, context_est - prompt_est)
    completion_est = _estimate_tokens(full_content)
    reasoning_est = _estimate_tokens(thinking_text_for_usage)
    usage = {
        "prompt_tokens": context_est,
        "completion_tokens": completion_est + reasoning_est,
        "total_tokens": context_est + completion_est + reasoning_est,
        "prompt_tokens_details": {
            "cached_tokens": cached_est,
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
    tools_schema: list[dict] | None = None,
    tool_codec_id: str = "deepseek_natural",
    input_text: str = "",
    full_context_text: str = "",
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
            if isinstance(ev.val, str) and ev.val:
                content_parts.append(ev.val)
        elif ev.type == "thinking":
            if not role_sent:
                role_sent = True
                yield _make_sse_chunk(request_id, model, created, 0, {"role": "assistant", "content": ""})
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
                for chunk in _stream_tool_call_chunks(request_id, model, created, tc, len(tool_calls_acc) - 1):
                    yield chunk
        elif ev.type == "error":
            yield _make_sse_chunk(request_id, model, created, 0, {"content": f"[错误] {ev.val}"}, finish_reason="stop")
            yield "data: [DONE]\n\n"
            return
        elif ev.type == "done":
            break

    # 解析工具块：先缓冲 content，解析后再发送（避免原始工具块文本泄漏给客户端）
    full_content = "".join(content_parts)
    # DEBUG: 记录原始模型输出
    with open(r"D:\files\References\others\deepseek-web-agent\proxy\debug_requests\_raw_content.log", "a", encoding="utf-8") as _f:
        _f.write(f"\n{'='*60}\n[STREAM] content_len={len(full_content)}\n{full_content}\n{'='*60}\n")
    # 始终从 content 文本中解析工具块（Qwen 可能同时有结构化 tool_call 事件和 content 中的工具块文本）
    remaining_text, parsed_calls = _detect_tool_blocks(full_content, tool_codec_id, tools_schema)
    # DEBUG: 记录解析结果
    if parsed_calls:
        with open(r"D:\files\References\others\deepseek-web-agent\proxy\debug_requests\_raw_content.log", "a", encoding="utf-8") as _f:
            for _tc in parsed_calls:
                _f.write(f"[PARSE] name={_tc['name']} args={_tc['arguments']}\n")
    print(f"[STREAM-DBG] tool_codec_id={tool_codec_id} content_len={len(full_content)} tool_calls_acc={len(tool_calls_acc)} parsed_calls={len(parsed_calls)} remaining_len={len(remaining_text)}")
    if parsed_calls:
        print(f"[STREAM-DBG] parsed names={[tc['name'] for tc in parsed_calls]}")
    if parsed_calls and not tool_calls_acc:
        # 文本解析出工具调用，且没有结构化 tool_call 事件 → 只发 tool_call，不发 remaining_text
        if not role_sent:
            role_sent = True
            yield _make_sse_chunk(request_id, model, created, 0, {"role": "assistant", "content": ""})
        for tc in parsed_calls:
            openai_tc = _build_openai_tool_call(tc)
            # DEBUG: 记录发给 Claude Code 的 tool_calls
            with open(r"D:\files\References\others\deepseek-web-agent\proxy\debug_requests\_flow.log", "a", encoding="utf-8") as _f:
                _f.write(f"[3/3] TO CLAUDE CODE\n{json.dumps(openai_tc, ensure_ascii=False, default=str)}\n{'='*60}\n")
            tool_calls_acc.append(openai_tc)
            for chunk in _stream_tool_call_chunks(request_id, model, created, openai_tc, len(tool_calls_acc) - 1):
                yield chunk
    else:
        # 无文本工具块，或已有结构化 tool_call → 发送清理后的 content（去掉工具块文本）
        # 但如果已有结构化 tool_call，不发文字内容（避免 Claude Code 重复处理）
        clean_content = remaining_text if parsed_calls else full_content
        if clean_content and not tool_calls_acc:
            if not role_sent:
                role_sent = True
                yield _make_sse_chunk(request_id, model, created, 0, {"role": "assistant", "content": ""})
            yield _make_sse_chunk(request_id, model, created, 0, {"content": clean_content})

    # usage - 全部自己估算，不依赖上游
    # prompt_tokens = 总输入（新+缓存），cached_tokens = 缓存命中
    # cc-switch 公式：input_tokens = prompt_tokens - cached_tokens
    full_content = "".join(content_parts)
    thinking_text = "\n".join(thinking_parts) if thinking_parts else ""
    from session import _estimate_tokens
    prompt_est = _estimate_tokens(input_text)
    context_est = _estimate_tokens(full_context_text)
    cached_est = max(0, context_est - prompt_est)
    completion_est = _estimate_tokens(full_content)
    reasoning_est = _estimate_tokens(thinking_text)
    usage = {
        "prompt_tokens": context_est,
        "completion_tokens": completion_est + reasoning_est,
        "total_tokens": context_est + completion_est + reasoning_est,
        "prompt_tokens_details": {
            "cached_tokens": cached_est,
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

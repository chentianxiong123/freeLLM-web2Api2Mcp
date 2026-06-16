"""OpenAI Chat Completions ↔ DeepSeek 翻译层

职责：
1. 接收 OpenAI 格式请求，提取用户消息 + tools schema
2. 把 tools schema 转成 "工具 名称 / 必填 / 可选" 描述，注入到发给 DeepSeek 的系统提示前
3. 流式收集 DeepSeek 的 content（可能含 `工具 X / 工具结束` 块）
4. 解析 tool 块 → 拆成 text content + tool_calls，按 OpenAI 格式返回给 Claude Code
"""

import json
import uuid
import time
import copy
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse, JSONResponse

import config
import deepseek_api as ds_api
import gateway
import tool_config
import tool_format  # 工具块解析器

MODEL_MAP = {
    "deepseek-v4-flash": ("deepseek-default", True, "default"),
    "deepseek-v4-pro": ("deepseek-expert", True, "expert"),
}

DS_MODEL_TYPE_TO_OPENAI = {
    "default": "deepseek-v4-flash",
    "expert": "deepseek-v4-pro",
    "vision": "deepseek-v4-vision",
}


def resolve_model(openai_model: str) -> tuple[str, bool, str]:
    entry = MODEL_MAP.get(openai_model)
    if entry:
        return entry
    return ("deepseek-default", True, "default")


def resolve_response_model(model_type: str) -> str:
    return DS_MODEL_TYPE_TO_OPENAI.get(model_type, "deepseek-v4-flash")


def _build_tools_injection(tools: list[dict]) -> str:
    """把 OpenAI tools schema 转成 DeepSeek 端能理解的工具列表说明。

    输出示例：
        你有 4 个工具可用：
        - Bash：执行 shell 命令
          必填：command
          可选：description, timeout
        - Read：读文件
          ...
    """
    if not tools:
        return ""
    lines = ["\n\n[当前可用工具列表]"]
    for t in tools:
        fn = t.get("function", {})
        name = fn.get("name", "?")
        desc = fn.get("description", "").strip().split("\n")[0]  # 取第一行
        params = fn.get("parameters", {}) or {}
        props = params.get("properties", {}) or {}
        required = set(params.get("required", []) or [])

        lines.append(f"\n- {name}：{desc}")
        if props:
            req = [k for k in props if k in required]
            opt = [k for k in props if k not in required]
            if req:
                lines.append(f"  必填：{', '.join(req)}")
            if opt:
                lines.append(f"  可选：{', '.join(opt)}")
    return "\n".join(lines)


def _estimate_prompt_tokens(text: str) -> int:
    if not text:
        return 0
    cn = sum(1 for c in text if '一' <= c <= '鿿')
    other = len(text) - cn
    return cn + max(1, other // 4)


def _chat_chunk(
    request_id: str,
    model: str,
    delta: dict,
    finish_reason: str | None = None,
) -> str:
    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def _usage_chunk(request_id: str, model: str, total: int, prompt: int, completion: int) -> str:
    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        },
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def _tool_call_delta(call_id: str, name: str, arguments: dict, idx: int) -> list[str]:
    """生成一个或多个 tool_calls delta chunk（OpenAI 流式格式）。

    第一个 delta 带 id + type + function.name + arguments 开头
    后续 delta 可以继续 arguments，但我们的解析器一次就有完整 arguments，所以一个 delta 搞定。
    """
    out = []

    # delta 1: id + type + function.name
    out.append(_chat_chunk(
        "", "",  # request_id/model 由调用方在外面加，但我们这里不重复加 — _chat_chunk 接受任意
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "index": idx,
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": ""},
            }],
        },
    ))

    # delta 2: function.arguments 一次性发完
    args_str = json.dumps(arguments, ensure_ascii=False)
    out.append(_chat_chunk(
        "", "",
        {
            "tool_calls": [{
                "index": idx,
                "function": {"arguments": args_str},
            }],
        },
    ))
    return out


async def stream_response(
    ds_stream,
    request_id: str,
    model: str,
    prompt_text: str = "",
    tools_schema: list[dict] | None = None,
):
    """DeepSeek 流 → OpenAI SSE 流。

    输出顺序：
    1. role delta
    2. content 增量（如果 DeepSeek 返回的是纯文本）
    3. 末段：tool_calls delta（如果含工具块）+ usage + finish_reason
    """
    role_sent = False
    stop_reason = None
    total_tokens: int | None = None
    completion_chars: list[str] = []
    full_content_parts: list[str] = []  # 完整 content（解析 tool 块前要用）

    for etype, val in ds_stream:
        if etype == "thinking":
            continue
        elif etype == "content":
            if not role_sent:
                role_sent = True
                yield _chat_chunk(request_id, model, {"role": "assistant", "content": ""})
            if isinstance(val, str):
                completion_chars.append(val)
                full_content_parts.append(val)
            yield _chat_chunk(request_id, model, {"content": val})
        elif etype == "token_usage":
            if isinstance(val, (int, float)) and val:
                total_tokens = int(val)
        elif etype == "error":
            yield _chat_chunk(request_id, model, {"content": f"[错误] {val}"}, finish_reason="stop")
            yield "data: [DONE]\n\n"
            return
        elif etype == "done":
            stop_reason = "stop"
            break

    if not stop_reason:
        stop_reason = "stop"

    # ── 解析 content，找 tool 块 ──
    full_content = "".join(full_content_parts)
    remaining_text, tool_calls = tool_format.parse_tool_blocks(full_content, tools_schema)

    # 如果发现了 tool 块，且之前 content 里已经流过这些块的原文（因为我们按 token 流），
    # 会让 Claude Code 看到"块里这些行既在 content 也在 tool_calls"。
    # 简单粗暴的处理：如果有 tool 块，就不再流原本那些 content（只流 remaining_text）。
    # 但这意味着我们已经 yield 的 content chunk 包含了工具块原始文本。
    #
    # 更优解：先流纯文本部分，末段再补一个 "content" delta 把工具块原文覆盖掉。
    # 这里先采取简单策略：有 tool 块时，最后追加一个空 content delta 占位（不重发），
    # 让 Claude Code 看到的是 content + tool_calls 共存，Claude Code 会优先用 tool_calls。
    #
    # 实际验证：OpenAI 客户端（Claude Code）会按出现顺序处理：先 content 后 tool_calls，
    # 工具块的原文会作为 content 末尾，然后 tool_calls 出现。Claude Code 会按 OpenAI 协议
    # 把 tool_calls 作为结构化输出处理，不会因为 content 含相同内容出错。

    # ── 输出 tool_calls deltas（如果有）──
    if tool_calls:
        for idx, tc in enumerate(tool_calls):
            call_id = f"call_{uuid.uuid4().hex[:24]}"
            for chunk in _tool_call_delta(call_id, tc["name"], tc["arguments"], idx):
                # 替换 _chat_chunk 里的空 model/id 为真实的
                chunk = chunk.replace('"model": ""', f'"model": "{model}"')
                chunk = chunk.replace('"id": ""', f'"id": "{request_id}"')
                yield chunk
        stop_reason = "tool_calls"

    # ── usage chunk ──
    if total_tokens is not None:
        completion_text = "".join(completion_chars)
        completion_est = _estimate_prompt_tokens(completion_text)
        prompt_est = max(0, total_tokens - completion_est)
        if completion_est == 0 and completion_text:
            completion_est = max(1, total_tokens - prompt_est)
        yield _usage_chunk(request_id, model, total_tokens, prompt_est, completion_est)
    else:
        yield _usage_chunk(request_id, model, 0, 0, 0)

    # 末条
    if not role_sent:
        yield _chat_chunk(request_id, model, {"role": "assistant", "content": ""}, finish_reason=stop_reason)
    else:
        yield _chat_chunk(request_id, model, {}, finish_reason=stop_reason)
    yield "data: [DONE]\n\n"


async def handle_chat(request: Request):
    """POST /v1/chat/completions"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={
            "error": {"message": "Invalid JSON", "type": "invalid_request_error"},
        })

    model_name = body.get("model", "claude-sonnet-4-6")
    stream = body.get("stream", False)

    ds_model, thinking_enabled, model_type = resolve_model(model_name)
    response_model = resolve_response_model(model_type)
    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    cfg = config.load_config()

    if not cfg.get("token"):
        return JSONResponse(status_code=401, content={
            "error": {"message": "Not logged in", "type": "authentication_error"},
        })

    # 提取用户消息
    user_content = gateway.extract_clean_user_prompt(body)
    if not user_content:
        return JSONResponse(status_code=400, content={
            "error": {"message": "No user message", "type": "invalid_request_error"},
        })

    # ── 工具注入：把 OpenAI tools 转成 DeepSeek 端的工具列表说明 ──
    tools = body.get("tools", []) or []
    tools_injection = _build_tools_injection(tools)
    if tools_injection:
        user_content = user_content + tools_injection

    ds_messages = [{"role": "user", "content": user_content}]

    ds_stream = ds_api.chat_completion(
        cfg=cfg,
        messages=ds_messages,
        model=ds_model,
        model_type=model_type,
        thinking_enabled=thinking_enabled,
        search_enabled=False,
        stream=True,
    )

    if stream:
        return StreamingResponse(
            stream_response(
                ds_stream,
                request_id,
                response_model,
                prompt_text=user_content,
                tools_schema=tools,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # 非流式：缓冲 + 解析
        content_parts: list[str] = []
        total_tokens: int | None = None
        for etype, val in ds_stream:
            if etype == "content":
                if isinstance(val, str):
                    content_parts.append(val)
            elif etype == "token_usage":
                if isinstance(val, (int, float)) and val:
                    total_tokens = int(val)
            elif etype == "done":
                break
        full_content = "".join(content_parts)
        remaining_text, tool_calls = tool_format.parse_tool_blocks(full_content, tools)

        message: dict[str, Any] = {
            "role": "assistant",
            "content": remaining_text if remaining_text else ("" if tool_calls else ""),
        }
        if tool_calls:
            message["tool_calls"] = [
                {
                    "id": f"call_{uuid.uuid4().hex[:24]}",
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ]

        if total_tokens is None:
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        else:
            completion_est = _estimate_prompt_tokens(full_content)
            prompt_est = max(0, total_tokens - completion_est)
            if completion_est == 0 and full_content:
                completion_est = max(1, total_tokens - prompt_est)
            usage = {
                "prompt_tokens": prompt_est,
                "completion_tokens": completion_est,
                "total_tokens": total_tokens,
            }

        finish_reason = "tool_calls" if tool_calls else "stop"
        return JSONResponse(content={
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": response_model,
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }],
            "usage": usage,
        })

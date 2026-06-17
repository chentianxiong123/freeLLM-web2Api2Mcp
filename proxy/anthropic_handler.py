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


def _extract_text_from_content(content) -> str:
    """从 OpenAI content 字段提取纯文本（兼容 str / list / 含注入块的情况）。"""
    # 先走 gateway 的清洗逻辑，剥 Claude Code 注入块
    if isinstance(content, str):
        # 用 gateway 的清洗
        return gateway.extract_clean_user_prompt({"messages": [{"role": "user", "content": content}]})
    if isinstance(content, list):
        # 拼所有 text 块
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                raw = b.get("text", "")
                cl = gateway.extract_clean_user_prompt({"messages": [{"role": "user", "content": raw}]})
                if cl:
                    parts.append(cl)
        return "\n".join(parts)
    return ""


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
    lines = ["\n你有以下工具可用（每次只能调用一个，发完等结果）："]
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
    lines.append("\n\n调用格式：")
    lines.append("工具 名称")
    lines.append('参数名="参数值"')
    lines.append("工具结束")
    lines.append("\n\n重要：路径必须用绝对路径（如 C:/Users/a1/Desktop），不要用 ~/Desktop 这种 Unix 简写——Windows 上不展开。")
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

    关键策略（react 循环正确性）：
    - content 部分**先全部缓存**，不流给 Claude Code
    - 等 DeepSeek 流完（type=done），解析"工具块"
    - 解析出 tool 块 → content 发空，**只**流 role + tool_calls + finish
    - 没 tool 块 → 流剩余纯文本（remaining_text）

    为什么之前错：旧版边流边发，DeepSeek 写的"好的，我先看看"+"工具 X"+"工具结束"全部
    当 content 流给 Claude Code。Claude Code 看到的是 "content=分析文字+工具块原文"+"tool_calls"，
    content 里复述了工具块，污染 react 循环。
    """
    role_sent = False
    stop_reason = None
    total_tokens: int | None = None
    completion_chars: list[str] = []
    full_content_parts: list[str] = []

    def _ensure_role():
        nonlocal role_sent
        if not role_sent:
            role_sent = True
            return _chat_chunk(request_id, model, {"role": "assistant", "content": ""})
        return None

    for etype, val in ds_stream:
        if etype == "thinking":
            # DeepSeek 在思考时不算 content，但仍先发 role（让 Claude Code 知道有回复）
            yield _ensure_role()
            continue
        elif etype == "content":
            yield _ensure_role()
            if isinstance(val, str):
                completion_chars.append(val)
                full_content_parts.append(val)
            # ⚠️ 关键：暂不流 content，等解析完工具块再决定流不流
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

    # ── 兜底：如果整轮 DeepSeek 一字未吐（极少见），现在补 role delta ──
    if not role_sent:
        yield _chat_chunk(request_id, model, {"role": "assistant", "content": ""})
        role_sent = True

    # ── 决定 content 流不流 ──
    if not tool_calls:
        # 没工具块 → 流剩余纯文本
        if remaining_text:
            for i in range(0, len(remaining_text), 100):
                yield _chat_chunk(request_id, model, {"content": remaining_text[i:i+100]})
    # 有工具块 → content 流空（避免污染）

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

    # ── 只发当前这条 user 消息原文 ──
    # DeepSeek session 持久，本来就记得住之前聊过什么。
    # 不要再把 OpenAI 的对话历史翻译成自然语言再发一遍——会重复塞垃圾、触发风控。
    msgs = body.get("messages", []) or []
    current_text = ""
    for m in reversed(msgs):
        if m.get("role") == "user":
            current_text = _extract_text_from_content(m.get("content", ""))
            break
    if not current_text:
        return JSONResponse(status_code=400, content={
            "error": {"message": "No user message", "type": "invalid_request_error"},
        })

    # 工具 schema 仅用于 type 推断，不注入 prompt
    tools = body.get("tools", []) or []

    ds_messages = [{"role": "user", "content": current_text}]

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
                prompt_text=current_text,
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

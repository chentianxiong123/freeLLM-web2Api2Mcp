"""OpenAI Chat Completions ↔ DeepSeek 纯聊天翻译层

只做一件事：扔掉 Claude Code 的系统提示词，把用户消息转发给 DeepSeek。
"""

import json
import uuid
import time
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse, JSONResponse

import config
import deepseek_api as ds_api
import gateway  # 引入网关的工具函数，确保执行路径与审批预览使用完全相同的清洗逻辑

MODEL_MAP = {
    "deepseek-v4-flash": ("deepseek-default", True, "default"),
    "deepseek-v4-pro": ("deepseek-expert", True, "expert"),
}


def resolve_model(openai_model: str) -> tuple[str, bool, str]:
    """OpenAI 模型名 → (DeepSeek 模型名, thinking_enabled, model_type)。"""
    entry = MODEL_MAP.get(openai_model)
    if entry:
        return entry
    return ("deepseek-default", True, "default")


# DeepSeek model_type → 公开的 OpenAI 模型名（用于响应里回显）
# 客户端期望看到「实际跑的那个模型」的名字，而不是它自己发的名字（Claude Code 发 claude-sonnet 我们不能回 claude-sonnet）
DS_MODEL_TYPE_TO_OPENAI = {
    "default": "deepseek-v4-flash",
    "expert": "deepseek-v4-pro",
    "vision": "deepseek-v4-vision",
}


def resolve_response_model(model_type: str) -> str:
    """DeepSeek 实际用的 model_type → 响应里返回的 OpenAI 模型名。"""
    return DS_MODEL_TYPE_TO_OPENAI.get(model_type, "deepseek-v4-flash")


def _estimate_prompt_tokens(text: str) -> int:
    """估算 prompt token 数（粗略）。

    经验公式（OpenAI cl100k_base 编码大致符合）：
    - 中文字符：1 字符 ≈ 1 token
    - 英文字符：4 字符 ≈ 1 token
    - 数字/标点：3 字符 ≈ 1 token

    注意：DeepSeek 端实际 token 数可能不同（他们用自家 tokenizer），
    但我们没有 token_usage 字段拆出 prompt vs completion，
    所以用估算至少给 OpenAI 客户端一个能看的数字。
    """
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
    """构造 OpenAI SSE chunk。"""
    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def _usage_chunk(request_id: str, model: str, total: int, prompt: int, completion: int) -> str:
    """构造 OpenAI SSE chunk 携带 usage 字段。"""
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


async def stream_response(ds_stream, request_id: str, model: str, prompt_text: str = ""):
    """DeepSeek 流 → OpenAI SSE 流。

    prompt_text: 用于估算 prompt_tokens（如果传入了）
    total_tokens 来自 DeepSeek accumulated_token_usage 终值（真实数字）
    completion 估算 = response 实际字符数
    prompt 估算 = total - completion（不会 < 0）
    """
    role_sent = False
    stop_reason = None
    total_tokens: int | None = None
    completion_chars: list[str] = []  # 累加响应内容

    for etype, val in ds_stream:
        if etype == "thinking":
            # OpenAI 没有 thinking 字段，跳过或塞进 content
            continue
        elif etype == "content":
            if not role_sent:
                role_sent = True
                yield _chat_chunk(request_id, model, {"role": "assistant", "content": ""})
            if isinstance(val, str):
                completion_chars.append(val)
            yield _chat_chunk(request_id, model, {"content": val})
        elif etype == "token_usage":
            # DeepSeek 端 accumulated_token_usage 终值 = 本次请求 input+output 总数（真实）
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

    # 流式：end-of-stream 时 yield 一个 usage chunk
    # prompt / completion 都是估算（DeepSeek 只给总数）
    if total_tokens is not None:
        completion_text = "".join(completion_chars)
        completion_est = _estimate_prompt_tokens(completion_text)
        # prompt 估算：total - completion（如果 completion 估大了，prompt 可能为 0）
        prompt_est = max(0, total_tokens - completion_est)
        # 如果 completion 估小得离谱（实际 completion 更大），把差值补到 completion
        if completion_est == 0 and completion_text:
            # 兜底：至少给 completion 1 token
            completion_est = max(1, total_tokens - prompt_est)
        yield _usage_chunk(request_id, model, total_tokens, prompt_est, completion_est)
    else:
        # 没拿到 token_usage，返回 0（避免发送 None）
        yield _usage_chunk(request_id, model, 0, 0, 0)

    # 最后一条
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
    # 响应里返回的 model：实际用的 DeepSeek 模型（不是 Claude Code 发的名字）
    response_model = resolve_response_model(model_type)
    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    cfg = config.load_config()

    if not cfg.get("token"):
        return JSONResponse(status_code=401, content={
            "error": {"message": "Not logged in", "type": "authentication_error"},
        })

    # 使用与网关审批预览完全一致的清洗逻辑，提取最终要发给 DeepSeek 的干净 prompt。
    # 保证“管理员在 /admin 看到的最新用户消息”和“实际放行后发出去的 prompt”完全一样。
    user_content = gateway.extract_clean_user_prompt(body)

    if not user_content:
        return JSONResponse(status_code=400, content={
            "error": {"message": "No user message", "type": "invalid_request_error"},
        })

    # 构造给 deepseek_api 的最小 wrapper，内部会取 messages[-1]["content"] 作为 prompt
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
            stream_response(ds_stream, request_id, response_model, prompt_text=user_content),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # 非流式：缓冲全部内容 + 抓 token_usage
        content_parts = []
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
        # prompt / completion 都是估算（DeepSeek 只给 total）
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
        return JSONResponse(content={
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": response_model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": full_content},
                "finish_reason": "stop",
            }],
            "usage": usage,
        })

"""Chat 编排层。

把 main.py 路由里的"接 OpenAI body → 调 Provider → 返回 OpenAI SSE"逻辑抽出来。

主流程：
  1. build_ds_input(body) → ChatRequest（判 react 续接 + 构造 DS 输入）
  2. provider.chat(messages) → AsyncIterator[Event]
  3. stream_events_to_openai(events) → AsyncIterator[str]（SSE）

不变量：
  - housekeeping 请求不进 provider，直接返回空 stop
  - rule-blocked 请求不进 provider，直接返回空 stop
  - 一切通过 → 走 provider → 7 条不变式由 stream_events_to_openai 保证
"""

import json
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator

from core.react_loop import build_ds_input, stream_events_to_openai
from providers.base import Event


# ── 拦截：housekeeping / rules ─────────────────────────


def check_housekeeping(body: dict) -> bool:
    """Claude Code 后台 housekeeping？直接挡。"""
    try:
        import gateway
        return gateway.is_claude_housekeeping_request(body)
    except Exception:
        return False


def check_rules(body: dict) -> tuple[bool, dict | None]:
    """可配置规则引擎拦截。返回 (是否拦截, 命中的规则)。"""
    try:
        import gateway
        import rules
        clean_prompt = gateway.extract_clean_user_prompt(body)
        return rules.is_blocked(body, clean_prompt)
    except Exception:
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


# ── 主入口 ──────────────────────────────────────────


async def stream_chat_to_sse(
    provider,                 # ChatProvider
    body: dict,
    *,
    request_id: str | None = None,
) -> AsyncIterator[str]:
    """把 OpenAI body → Provider → SSE 流。

    返回 AsyncIterator[str]，每个元素是一个 SSE data: 行。
    """
    if request_id is None:
        request_id = "chatcmpl-" + uuid.uuid4().hex[:12]

    model = body.get("model", "deepseek-v4-flash")
    tools = body.get("tools", []) or []

    # 1. 拦截
    if check_housekeeping(body):
        skip = make_skip_response(model, request_id, "housekeeping")
        yield "data: " + json.dumps({
            "id": skip["id"],
            "object": "chat.completion.chunk",
            "created": skip["created"],
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
        }, ensure_ascii=False) + "\n\n"
        yield "data: " + json.dumps({
            "id": skip["id"],
            "object": "chat.completion.chunk",
            "created": skip["created"],
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
        return

    blocked, _ = check_rules(body)
    if blocked:
        skip = make_skip_response(model, request_id, "rule")
        yield "data: " + json.dumps({
            "id": skip["id"],
            "object": "chat.completion.chunk",
            "created": skip["created"],
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
        }, ensure_ascii=False) + "\n\n"
        yield "data: " + json.dumps({
            "id": skip["id"],
            "object": "chat.completion.chunk",
            "created": skip["created"],
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
        return

    # 2. body → DS 输入
    req = build_ds_input(body)
    if not req.user_content:
        # 没 user 也没 tool — 空请求
        yield "data: " + json.dumps({
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": "stop"}],
        }, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
        return

    # 3. 调 Provider
    messages = [{"role": "user", "content": req.user_content}]

    # 解析 model 名
    provider_model = _resolve_provider_model(model)

    events = provider.chat(
        messages,
        model=provider_model,
        thinking_enabled=True,
        search_enabled=False,
    )

    # 4. Event 流 → SSE
    async for sse in stream_events_to_openai(
        events,
        request_id=request_id,
        model=model,
        tools_schema=tools,
    ):
        yield sse


def _resolve_provider_model(openai_model: str) -> str:
    """OpenAI model 名 → Provider 内部 model 名。

    临时实现：保持兼容，等 DeepSeekProvider 写完再换。
    """
    # 默认就是 provider 自己的 default
    return openai_model

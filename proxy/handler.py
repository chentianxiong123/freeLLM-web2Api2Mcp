"""Chat 编排层

合并 chat_handler + react_loop 为统一模块。

两个核心功能：
  1. build_ds_input(body) → ChatRequest
     决定 body 是"react 续接"还是"新对话"，并构造发给 Provider 的消息

  2. stream_chat_to_sse(provider, body, ...) → AsyncIterator[str]
     把 OpenAI body → Provider → OpenAI Chat Completions SSE 格式
     严格执行 7 条不变式

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

    print(f"[build_ds_input] msgs count={len(msgs)}, has_tool={has_tool}")
    for i, m in enumerate(msgs):
        role = m.get("role", "?")
        content = m.get("content", "")
        preview = content[:100].replace('\n', ' ') if isinstance(content, str) else str(content)[:100]
        print(f"[build_ds_input]   [{i}] role={role}, content_preview={preview}")
        if role == "tool":
            print(f"[build_ds_input]   >>> TOOL MESSAGE FOUND <<<")

    if has_tool:
        # ── react 续接：直接返回工具结果，按顺序 ──
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
            tool_msgs.append(text)
        # 按顺序返回，不标号，AI 应知道顺序
        user_content = "\n\n".join(tool_msgs)
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


# ── 2. 拦截：housekeeping / rules ─────────────────────────


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


# ── 3. SSE 辅助函数 ──────────────────────────────────────


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


# ── 4. Provider Event → OpenAI SSE ─────────────────────


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
            # 将 thinking 内容作为 content 发送给客户端
            if isinstance(ev.val, str) and ev.val:
                full_content_parts.append(ev.val)
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


# ── 5. 收集完整响应 ──────────────────────────────────────


async def collect_response(
    events: AsyncIterator[Event],
    *,
    request_id: str,
    model: str,
    tools_schema: list[dict] | None = None,
) -> dict:
    """收集所有事件，返回完整的 OpenAI 响应 dict（非流式）。"""
    thinking_parts: list[str] = []
    content_parts: list[str] = []
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
            tc_name = ev.val.get("name", "?") if isinstance(ev.val, dict) else "?"
            tc_args = ev.val.get("arguments", {}) if isinstance(ev.val, dict) else {}
            content_parts.append(f"工具 {tc_name}\n")
            for k, v in tc_args.items():
                content_parts.append(f'{k}="{v}"\n')
            content_parts.append("工具结束\n")
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

    # 解析 content，找 tool 块
    full_content = "".join(content_parts)
    remaining_text, tool_calls = _detect_tool_blocks(full_content)

    # 构建 message
    message = {"role": "assistant"}
    if tool_calls:
        message["content"] = remaining_text or None
        message["tool_calls"] = tool_calls
        finish_reason = "tool_calls"
    else:
        message["content"] = remaining_text or full_content or None
        finish_reason = "stop"

    # thinking 内容（扩展字段，非标准）
    thinking_text = "\n".join(thinking_parts) if thinking_parts else None

    # usage
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

    # 如果有 thinking，加扩展字段
    if thinking_text:
        result["thinking"] = thinking_text

    return result


# ── 6. React 循环（本地执行 DeepSeek 工具调用）──────────────


MAX_REACT_ITERATIONS = 10


async def react_loop(
    provider,
    user_content: str,
    *,
    request_id: str,
    model: str,
    tools_schema: list[dict] | None = None,
    cwd: str | None = None,
) -> dict:
    """React 循环：发送消息给 DS，如果响应含 tool_calls 则本地执行并续接。

    流程：
      1. 发送 user_content 给 DS
      2. 收集响应，解析 tool_calls
      3. 如果有 tool_calls → 本地执行 → 把结果作为 user 消息发回 DS
      4. 重复直到 DS 返回纯文本（无 tool_calls）或达到最大迭代次数
      5. 返回最终的 OpenAI 响应 dict
    """
    from local_executor import execute_tool_calls as local_exec

    messages = [{"role": "user", "content": user_content}]

    for iteration in range(MAX_REACT_ITERATIONS):
        print(f"[react_loop] iteration={iteration+1}, sending {len(messages)} messages to DS")

        # 调 Provider
        events = provider.chat(
            messages,
            model=model,
            thinking_enabled=True,
            search_enabled=False,
        )

        # 收集所有事件
        collected_events = []
        async for ev in events:
            collected_events.append(ev)

        # 转为 OpenAI 响应 dict
        resp = await collect_response(
            _aiter(collected_events),
            request_id=request_id,
            model=model,
            tools_schema=tools_schema,
        )

        msg = resp.get("choices", [{}])[0].get("message", {})
        tool_calls = msg.get("tool_calls", [])

        if not tool_calls:
            # 无 tool_calls → 最终响应，直接返回
            print(f"[react_loop] no tool_calls, returning final response")
            return resp

        # 有 tool_calls → 本地执行
        print(f"[react_loop] got {len(tool_calls)} tool_calls, executing locally")
        results = local_exec(tool_calls, cwd=cwd)

        # 构造 DS 续接消息：把工具结果作为 user 消息发回，不标号
        result_text = "\n\n".join(results)
        messages.append({"role": "user", "content": result_text})

        print(f"[react_loop] tool results: {result_text[:200]}...")

    # 达到最大迭代次数 → 返回最后的响应
    print(f"[react_loop] reached max iterations ({MAX_REACT_ITERATIONS})")
    return resp


def _aiter(items):
    """把 list 包装成 async iterator。"""
    async def gen():
        for item in items:
            yield item
    return gen()


# ── 7. 主入口 ──────────────────────────────────────────


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

    # 4. 收集所有事件
    collected_events = []
    async for ev in events:
        collected_events.append(ev)

    # 5. Event 流 → SSE
    async for sse in stream_events_to_openai(
        iter(collected_events),
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

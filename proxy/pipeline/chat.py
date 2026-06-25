"""POST /v1/chat/completions 核心流程。"""

from __future__ import annotations

import time
import uuid

from fastapi.responses import JSONResponse, StreamingResponse

import accounts
import approval
from prompts import manager as prompt_manager
import rules
import session as sess
from agents.registry import get_agent
from backends.registry import get_backend
from handler import collect_response, make_skip_response
from core.types import TurnRequest


_req_counter = 0


async def _reset_upstream_session(backend, rid: str):
    """compact 后台任务：重置续接点（不创建新会话）。"""
    try:
        import accounts as _acc
        cfg = _acc.get_account_config()
        session_id = cfg.get("session_id")
        if session_id:
            backend._continuation.reset(session_id)
            print(f"[{rid}] compact: continuation reset for session={session_id[:12]}...")
    except Exception as e:
        print(f"[{rid}] compact reset failed: {e}")


def _next_rid() -> tuple[str, str]:
    global _req_counter
    _req_counter += 1
    rid = f"R{_req_counter}"
    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    return rid, request_id


def _last_user_preview(msgs: list) -> str:
    for m in reversed(msgs):
        c = m.get("content", "")
        if isinstance(c, str):
            return c[:100].replace("\n", " ")
        if isinstance(c, list):
            for b in reversed(c):
                if isinstance(b, dict) and b.get("type") == "text":
                    return (b.get("text", "") or "")[:100].replace("\n", " ")
    return ""


async def run_chat_completion(
    *,
    body: dict,
    headers: dict[str, str],
) -> JSONResponse | StreamingResponse:
    backend = get_backend()
    agent = get_agent(headers=headers, body=body)

    rid, request_id = _next_rid()
    tools = body.get("tools", []) or []
    msgs = body.get("messages", []) or []
    request_model = body.get("model") or ""
    actual_model = backend.active_model()  # 后端实际使用的模型

    print(
        f"[{rid}] agent={agent.id} backend={backend.id} model={actual_model} "
        f"request_model={request_model} msgs={len(msgs)} last={_last_user_preview(msgs)}"
    )

    upstream_content, is_react, tool_ids = agent.extract_upstream_turn(body)
    stream = body.get("stream", False)

    if agent.is_housekeeping(body):
        print(f"[{rid}] BLOCKED housekeeping agent={agent.id}")
        if stream:
            from handler import stream_skip_response
            return StreamingResponse(
                stream_skip_response(actual_model, request_id),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )
        return JSONResponse(content=make_skip_response(actual_model, request_id, "housekeeping"))

    # ── 剥离 system-reminder（所有消息）──────────────────
    import gateway
    body = gateway.strip_system_reminders_from_messages(body)
    msgs = body.get("messages", []) or []

    # ── 检测 intercept 规则（如 /compact）────────────────
    intercept_rule = rules.find_intercept_rule(body)
    is_compact = intercept_rule is not None and intercept_rule.get("name") == "COMPACT"
    if is_compact:
        print(f"[{rid}] INTERCEPTED compact via rule={intercept_rule.get('id')}")

    clean_prompt = agent.clean_prompt_for_rules(body)
    blocked, hit_rule = rules.is_blocked(body, clean_prompt)
    if blocked:
        rule_name = hit_rule.get("name", "?") if hit_rule else "?"
        print(f"[{rid}] BLOCKED rule={rule_name}")
        if stream:
            from handler import stream_skip_response
            return StreamingResponse(
                stream_skip_response(actual_model, request_id),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )
        return JSONResponse(content=make_skip_response(actual_model, request_id, f"rule:{rule_name}"))

    turn = TurnRequest(
        body=body,
        headers=headers,
        model=actual_model,
        tools=tools,
        request_id=request_id,
        rid=rid,
        upstream_user_content=upstream_content,
        is_react_continuation=is_react,
        tool_call_ids=tool_ids,
        working_directory=body.get("working_directory", "") or body.get("cwd", ""),
    )

    req_result = await approval.queue.intercept_request(
        method="POST",
        path="/v1/chat/completions",
        body=body,
        headers=headers,
        conversion={
            "user_content": turn.upstream_user_content[:5000] if turn.upstream_user_content else "",
            "is_react_continuation": turn.is_react_continuation,
            "tool_call_ids": turn.tool_call_ids,
            "messages_count": len(msgs),
            "agent_id": agent.id,
            "backend_id": backend.id,
        },
    )
    if req_result["action"] == "reject":
        return JSONResponse(status_code=403, content={
            "error": {"message": req_result.get("error", "请求被拒绝"), "type": "permission_error"},
        })

    final_user_content = turn.upstream_user_content
    if req_result.get("edited") and req_result.get("body"):
        edited = req_result["body"]
        if isinstance(edited, dict) and "user_content" in edited:
            final_user_content = edited["user_content"]

    cleaned_content, _strip_hits = rules.clean_request_content(final_user_content)
    final_user_content = cleaned_content or "(empty after strip)"

    # 构建完整上下文文本（所有 messages 拼接），用于计算 cached_tokens
    full_context_text = ""
    for m in msgs:
        c = m.get("content", "")
        if isinstance(c, str):
            full_context_text += c + "\n"
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    full_context_text += (b.get("text", "") or "") + "\n"

    account_config = accounts.get_account_config()
    if not account_config.get("token"):
        return JSONResponse(status_code=401, content={
            "error": {"message": "No active account", "type": "authentication_error"},
        })

    # ── 系统提示词：仅根消息（无续接点）时注入 ─────────
    session_id = account_config.get("session_id")
    is_root = not backend._continuation.get_continuation_id(session_id)
    system_prompt = prompt_manager.build_system_prompt() if is_root else ""

    # ── compact：替换 user content 为压缩指令 ──────────
    if is_compact:
        final_user_content = prompt_manager.get_compact_instruction()
        system_prompt = prompt_manager.build_system_prompt()
        print(f"[{rid}] compact: replaced with instruction ({len(final_user_content)} chars)")

    stream = body.get("stream", False)
    t0 = time.time()

    if stream:
        captured_content: list[str] = []
        captured_thinking: list[str] = []

        async def _capture_events():
            async for ev in backend.chat_turn(
                final_user_content,
                model=actual_model,
                account_config=account_config,
                thinking_enabled=True,
                search_enabled=False,
                system_prompt=system_prompt,
            ):
                if ev.type == "content" and isinstance(ev.val, str):
                    captured_content.append(ev.val)
                elif ev.type == "thinking" and isinstance(ev.val, str):
                    captured_thinking.append(ev.val)
                yield ev

        from handler import stream_response as _sr

        async def _sse_stream():
            async for line in _sr(_capture_events(), request_id=request_id, model=actual_model, input_text=final_user_content, full_context_text=full_context_text):
                yield line
            output_text = "".join(captured_content)
            thinking_text = "".join(captured_thinking)
            sess.track_message(
                final_user_content,
                output_text,
                thinking_text=thinking_text,
                session_id=account_config.get("session_id"),
            )
            # compact 完成后：保存摘要 + 后台重置上游会话
            if is_compact:
                prompt_manager.set_compact_summary(output_text)
                print(f"[{rid}] compact summary saved ({len(output_text)} chars)")
                import asyncio
                asyncio.create_task(_reset_upstream_session(backend, rid))

        return StreamingResponse(
            _sse_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    collected = []
    async for ev in backend.chat_turn(
        final_user_content,
        model=actual_model,
        account_config=account_config,
        thinking_enabled=True,
        search_enabled=False,
        system_prompt=system_prompt,
    ):
        collected.append(ev)

    async def _iter(items):
        for item in items:
            yield item

    final_resp = await collect_response(
        _iter(collected),
        request_id=request_id,
        model=actual_model,
        tools_schema=tools,
        tool_codec_id=backend.tool_codec_id(),
        input_text=final_user_content,
        full_context_text=full_context_text,
    )

    output_text = final_resp.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
    thinking_text = final_resp.get("choices", [{}])[0].get("message", {}).get("reasoning_content", "") or ""
    filtered, hits = rules.filter_response(output_text)
    if filtered != output_text or hits:
        final_resp["choices"][0]["message"]["content"] = filtered or None

    sess.track_message(
        final_user_content,
        output_text,
        thinking_text=thinking_text,
        session_id=account_config.get("session_id"),
    )

    # compact 完成后：保存摘要 + 后台重置上游会话
    if is_compact:
        prompt_manager.set_compact_summary(output_text)
        print(f"[{rid}] compact summary saved ({len(output_text)} chars)")
        import asyncio
        asyncio.create_task(_reset_upstream_session(backend, rid))

    duration_ms = (time.time() - t0) * 1000

    resp_result = await approval.queue.intercept_response(
        request_item_id=0,
        status=200,
        body=final_resp,
        duration_ms=duration_ms,
    )
    if resp_result["action"] == "reject":
        return JSONResponse(status_code=403, content={
            "error": {"message": resp_result.get("error", "响应被拒绝"), "type": "permission_error"},
        })
    if resp_result.get("edited") and resp_result.get("body"):
        final_resp = resp_result["body"]

    ch = final_resp.get("choices", [{}])[0]
    print(
        f"[{rid}] DONE agent={agent.id} backend={backend.id} "
        f"duration={duration_ms:.0f}ms finish={ch.get('finish_reason', '?')} "
        f"tool_calls={bool(ch.get('message', {}).get('tool_calls'))}"
    )

    return JSONResponse(content=final_resp)
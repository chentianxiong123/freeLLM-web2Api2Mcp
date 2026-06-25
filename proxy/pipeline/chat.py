"""POST /v1/chat/completions 核心流程。"""

from __future__ import annotations

import time
import uuid

from fastapi.responses import JSONResponse, StreamingResponse

import accounts
import approval
import rules
import session as sess
from agents.registry import get_agent
from backends.registry import get_backend
from handler import collect_response, make_skip_response
from core.types import TurnRequest


_req_counter = 0


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
    model = body.get("model") or backend.active_model()

    print(
        f"[{rid}] agent={agent.id} backend={backend.id} model={model} "
        f"msgs={len(msgs)} last={_last_user_preview(msgs)}"
    )

    upstream_content, is_react, tool_ids = agent.extract_upstream_turn(body)

    if agent.is_housekeeping(body):
        print(f"[{rid}] BLOCKED housekeeping agent={agent.id}")
        return JSONResponse(content=make_skip_response(model, request_id, "housekeeping"))

    clean_prompt = agent.clean_prompt_for_rules(body)
    blocked, hit_rule = rules.is_blocked(body, clean_prompt)
    if blocked:
        rule_name = hit_rule.get("name", "?") if hit_rule else "?"
        print(f"[{rid}] BLOCKED rule={rule_name}")
        return JSONResponse(content=make_skip_response(model, request_id, f"rule:{rule_name}"))

    turn = TurnRequest(
        body=body,
        headers=headers,
        model=model,
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

    account_config = accounts.get_account_config()
    if not account_config.get("token"):
        return JSONResponse(status_code=401, content={
            "error": {"message": "No active account", "type": "authentication_error"},
        })

    stream = body.get("stream", False)
    t0 = time.time()

    if stream:
        captured_content: list[str] = []
        captured_thinking: list[str] = []

        async def _capture_events():
            async for ev in backend.chat_turn(
                final_user_content,
                model=model,
                account_config=account_config,
                thinking_enabled=True,
                search_enabled=False,
            ):
                if ev.type == "content" and isinstance(ev.val, str):
                    captured_content.append(ev.val)
                elif ev.type == "thinking" and isinstance(ev.val, str):
                    captured_thinking.append(ev.val)
                yield ev

        from handler import stream_response as _sr

        async def _sse_stream():
            async for line in _sr(_capture_events(), request_id=request_id, model=model):
                yield line
            output_text = "".join(captured_content)
            thinking_text = "".join(captured_thinking)
            sess.track_message(
                final_user_content,
                output_text,
                thinking_text=thinking_text,
                session_id=account_config.get("session_id"),
            )

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
        model=model,
        account_config=account_config,
        thinking_enabled=True,
        search_enabled=False,
    ):
        collected.append(ev)

    async def _iter(items):
        for item in items:
            yield item

    final_resp = await collect_response(
        _iter(collected),
        request_id=request_id,
        model=model,
        tools_schema=tools,
        tool_codec_id=backend.tool_codec_id(),
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
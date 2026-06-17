"""DeepSeek Web Agent Proxy — 入口文件

将 DeepSeek 网页端免费对话转换为 OpenAI Chat Completions API，
供 Claude Code（OpenAI 模式）作为后端模型使用。

特点：
- 单会话持久化，不新建
- 增量消息传递，依赖服务端上下文
- 网关审批：所有请求先挂起，管理员确认后才发送
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import json
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse

from core.chat_handler import stream_chat_to_sse
from providers.mock import ScriptedProvider, BashListProvider
import config
import deepseek_api as ds_api
import session as sess
import gateway
import rules
import tool_config
import tool_format
from admin_page import render_admin_html

app = FastAPI(
    title="DeepSeek Web Agent Proxy",
    version="0.1.0",
    description="DeepSeek 网页端 → OpenAI Chat Completions API 代理",
)


# ── 错误处理中间件 ──────────────────────────────────────


@app.middleware("http")
async def error_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "type": "internal_server_error",
                    "message": str(e),
                },
            },
        )


# ── 路由 ──────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI Chat Completions 端点 — v2 架构（react_loop + Provider）。

    旧版 200 行的 react 内联 + housekeeping + rules + handle_chat 全部委托给
    core.chat_handler.stream_chat_to_sse。

    行为：
      - housekeeping → 返空 stop
      - rules 拦截 → 返空 stop
      - 否则 → 调 _CURRENT_PROVIDER，stream 出来

    当前默认是 BashListProvider（mock），等 DeepSeekProvider 接入后可切换。
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={
            "error": {"message": "Invalid JSON", "type": "invalid_request_error"},
        })

    is_stream = bool(body.get("stream", True))
    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    if is_stream:
        async def gen():
            async for sse in stream_chat_to_sse(_CURRENT_PROVIDER, body, request_id=request_id):
                yield sse
        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
    else:
        # 非流式：收集 SSE → 拼成 JSON
        full_content = ""
        tool_calls = []
        finish_reason = "stop"
        async for sse in stream_chat_to_sse(_CURRENT_PROVIDER, body, request_id=request_id):
            line = sse.strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            try:
                chunk = json.loads(line[6:])
            except Exception:
                continue
            delta = chunk.get("choices", [{}])[0].get("delta", {})
            if "content" in delta and delta["content"]:
                full_content += delta["content"]
            if "tool_calls" in delta:
                for tc in delta["tool_calls"]:
                    if "id" in tc:
                        tool_calls.append({"id": tc["id"], "type": "function", "function": tc.get("function", {})})
            if chunk.get("choices", [{}])[0].get("finish_reason"):
                finish_reason = chunk["choices"][0]["finish_reason"]

        message = {"role": "assistant", "content": full_content or ("" if tool_calls else "")}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return JSONResponse(content={
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", "deepseek-v4-flash"),
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })


@app.get("/v1/models")
async def list_models():
    """返回可用模型列表（OpenAI 格式）。

    列出的是客户端可以请求的 OpenAI 模型名（不是 DeepSeek 内部 model_type）。
    内部路由：default -> deepseek-v4-flash, expert -> deepseek-v4-pro
    """
    models_data = [
        {"id": "deepseek-v4-flash", "object": "model", "created": 1700000000, "owned_by": "deepseek"},
        {"id": "deepseek-v4-pro", "object": "model", "created": 1700000000, "owned_by": "deepseek"},
    ]
    return {"object": "list", "data": models_data}


@app.get("/health")
async def health():
    """健康检查"""
    cfg = config.load_config()
    has_session = bool(cfg.get("session_id"))
    usage = sess.get_usage_status() if has_session else {}
    return {
        "status": "ok",
        "authenticated": bool(cfg.get("token")),
        "session_active": has_session,
        "usage": usage,
    }


# ── 审批 API ──────────────────────────────────────────


@app.get("/api/pending")
async def api_pending():
    """获取待审批请求列表"""
    return {"requests": gateway.get_pending_list()}


@app.get("/api/request/{req_id}")
async def api_request_detail(req_id: str):
    """获取单个请求的完整详情"""
    detail = gateway.get_request_detail(req_id)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return detail


@app.post("/api/approve/{req_id}")
async def api_approve(req_id: str):
    """放行请求"""
    ok = gateway.approve(req_id)
    return {"ok": ok, "id": req_id}


@app.post("/api/reject/{req_id}")
async def api_reject(req_id: str):
    """拒绝请求"""
    ok = gateway.reject(req_id)
    return {"ok": ok, "id": req_id}


# ── 测试触发器（调试用） ──────────────────────────────────────


@app.post("/api/test/mock")
async def api_test_mock(request: Request):
    """测试触发器：直接构造一个最小化的 OpenAI 请求走 mock 路径。

    用法：POST /api/test/mock，body 里可带 {"stream": true/false, "prompt": "你好"}
    默认 prompt = "你好"，stream = true。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    prompt = body.get("prompt", "你好")
    is_stream = bool(body.get("stream", True))
    model = body.get("model", "deepseek-v4-flash")

    fake_body = {
        "model": model,
        "stream": is_stream,
        "messages": [{"role": "user", "content": prompt}],
    }

    # 直接调用 chat_completions 让它走和 Claude Code 一样的分支
    fake_request = Request(scope={"type": "http", "method": "POST", "headers": []})
    fake_request._body = json.dumps(fake_body).encode("utf-8")
    return await chat_completions(fake_request)


# ── 违规拦截规则 API ──────────────────────────────


@app.get("/api/rules")
async def api_list_rules():
    """列出所有拦截规则。"""
    return {"rules": rules.list_rules()}


@app.post("/api/rules/add")
async def api_add_rule(request: Request):
    """新增规则。body: {name, type, pattern?, scope?, case_sensitive?, enabled?, note?}"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    new_rule = rules.add_rule(body)
    return {"ok": True, "rule": new_rule}


@app.post("/api/rules/update/{rule_id}")
async def api_update_rule(rule_id: str, request: Request):
    """部分更新规则。body: 任意字段。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    updated = rules.update_rule(rule_id, body)
    if not updated:
        return JSONResponse(status_code=404, content={"ok": False, "error": "rule 不存在"})
    return {"ok": True, "rule": updated}


@app.post("/api/rules/delete/{rule_id}")
async def api_delete_rule(rule_id: str):
    """删除规则。"""
    ok = rules.delete_rule(rule_id)
    return {"ok": ok, "id": rule_id}


@app.post("/api/rules/toggle/{rule_id}")
async def api_toggle_rule(rule_id: str, request: Request):
    """切换 enabled。body: {enabled?: bool}（不传则反转）"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    updated = rules.toggle_rule(rule_id, body.get("enabled"))
    if not updated:
        return JSONResponse(status_code=404, content={"ok": False, "error": "rule 不存在"})
    return {"ok": True, "rule": updated}


@app.post("/api/rules/reset")
async def api_reset_rules():
    """重置为默认规则集。"""
    new_rules = rules.reset_to_defaults()
    return {"ok": True, "rules": new_rules}


@app.post("/api/rules/test")
async def api_test_rules(request: Request):
    """测试：拿一段 user 消息 / body，看会被哪些规则命中。

    body: {prompt?: str, body?: dict}
    返回 {hits: [...], blocked: bool, first_hit?: {...}}
    """
    try:
        req_body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})

    # 构造一个 body
    body = req_body.get("body")
    if not isinstance(body, dict):
        prompt = req_body.get("prompt", "")
        body = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": prompt}],
        }

    clean_prompt = ""
    try:
        clean_prompt = gateway.extract_clean_user_prompt(body)
    except Exception:
        pass

    # 模拟 rules.is_blocked 的遍历但收集所有命中
    import json as _json
    full_body_text = _json.dumps(body, ensure_ascii=False, default=str) if body else ""

    hits = []
    blocked = False
    first_hit = None
    for r in rules.list_rules():
        if not r.get("enabled", True):
            continue
        rtype = r.get("type", "")
        scope = r.get("scope", "body")
        pattern = r.get("pattern", "")
        text = full_body_text if scope in ("body", "any") else clean_prompt

        matched = False
        if rtype == "empty_clean_prompt":
            matched = not clean_prompt.strip()
        elif pattern:
            haystack = text if r.get("case_sensitive", False) else text.lower()
            needle = pattern if r.get("case_sensitive", False) else pattern.lower()
            if rtype == "keyword_substring":
                matched = needle in haystack
            elif rtype == "regex":
                import re
                flags = 0 if r.get("case_sensitive", False) else re.IGNORECASE
                try:
                    matched = bool(re.search(pattern, text, flags))
                except re.error:
                    pass

        if matched:
            hits.append(r)
            if not blocked:
                blocked = True
                first_hit = r

    return {
        "ok": True,
        "clean_prompt_len": len(clean_prompt),
        "clean_prompt_preview": clean_prompt[:200],
        "blocked": blocked,
        "first_hit": first_hit,
        "hits": hits,
    }


# ── 工具调用配置 API ──────────────────────────────


@app.get("/api/tool-config")
async def api_get_tool_config():
    """获取工具定义列表 + 模板。"""
    cfg = tool_config.get_config()
    return {
        "template": cfg.get("template", ""),
        "tools": cfg.get("tools", {}),
    }


@app.post("/api/tool-config")
async def api_save_tool_config(request: Request):
    """保存工具定义和模板。body: {template?: str, tools?: dict}"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    data = tool_config.update_config(body)
    return {"ok": True, "template": data.get("template", "")[:80]+"…", "tool_count": len(data.get("tools", {}))}


@app.post("/api/tool-config/init")
async def api_init_tools(request: Request):
    """发送初始化消息给 DeepSeek（建立游戏语境）。"""
    cfg = config.load_config()
    if not cfg.get("token"):
        return JSONResponse(status_code=401, content={"ok": False, "error": "未登录"})
    if not cfg.get("session_id"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "没有 active session"})

    prompt = tool_config.build_init_prompt()
    print(f"[ToolInit] 发送初始化消息（{len(prompt)} 字符）到 session {cfg['session_id'][:16]}...")

    ds_messages = [{"role": "user", "content": prompt}]
    ds_model = "deepseek-default"
    model_type = "default"

    old_mid = sess.get_last_message_id()
    if old_mid:
        sess.clear_last_message_id()
        print(f"[ToolInit] 清除了旧续接点 parent_message_id={old_mid}")

    ds_stream = ds_api.chat_completion(
        cfg=cfg,
        messages=ds_messages,
        model=ds_model,
        model_type=model_type,
        thinking_enabled=True,
        search_enabled=False,
        stream=True,
    )

    full_content = ""
    got_message_id = None
    for etype, val in ds_stream:
        if etype == "content":
            full_content += val if isinstance(val, str) else ""
        elif etype == "message_id":
            got_message_id = val
            print(f"[ToolInit] DeepSeek 返回 message_id={val}")

    preview = (full_content[:100].replace('\n', ' ') + '…') if len(full_content) > 100 else full_content.replace('\n', ' ')
    print(f"[ToolInit] 响应：{preview}")

    if got_message_id:
        sess.set_last_message_id(got_message_id)
        sess.increment_message_count()

    return {
        "ok": True,
        "message": "初始化消息已发送",
        "response_preview": preview[:200],
        "response_length": len(full_content),
        "message_id": got_message_id,
    }


# ── Session 管理 API ──────────────────────────────────────


@app.get("/api/sessions")
async def api_list_sessions():
    """列出所有 session（含 active 标记 + message_count / last_used）。"""
    return {"sessions": sess.list_sessions()}


@app.post("/api/sessions/new")
async def api_new_session(request: Request):
    """新建 session（调 DeepSeek /chat_session/create，注册到列表并激活）。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    label = body.get("label", "")

    cfg = config.load_config()
    if not cfg.get("token"):
        return JSONResponse(status_code=401, content={"ok": False, "error": "未登录"})

    new_sid = ds_api.create_new_session(cfg)
    if not new_sid:
        return JSONResponse(status_code=500, content={"ok": False, "error": "创建 session 失败"})

    sess.register_session(new_sid, label=label)
    sess.activate_session(new_sid)
    return {"ok": True, "session_id": new_sid, "label": label}


@app.post("/api/sessions/activate")
async def api_activate_session(request: Request):
    """切换 active session（写 sessions.json + config.json，下次请求走新 session）。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})

    sid = body.get("session_id", "")
    if not sid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "session_id required"})

    ok = sess.activate_session(sid)
    return {"ok": ok, "session_id": sid if ok else None, "error": None if ok else "session 不存在"}


# ── 管理页面 ──────────────────────────────────────────


@app.get("/admin")
async def admin():
    """管理控制台页面。"""
    cfg = config.load_config()
    usage = sess.get_usage_status() if cfg.get("session_id") else {}
    return HTMLResponse(render_admin_html(cfg, usage))
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin")


@app.post("/login")
async def login(request: Request):
    """登录 DeepSeek 并创建持久会话。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})

    login_type = body.get("login_type", "email")
    password = body.get("password", "")
    account = body.get("account", "") or body.get("email", "") or body.get("mobile", "")
    if not account or not password:
        return JSONResponse(status_code=400, content={"ok": False, "error": "account and password required"})

    result = ds_api.login(login_type, account, password)
    if result:
        return {"ok": True, "message": "Login successful, session created"}
    else:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Login failed. Check console for details."})


# ── v2 架构：新 react_loop + Provider ───────────────────────


# 当前使用的 provider（启动时由环境变量决定）
# DEEPSEEK_PROVIDER=true → 用真实 DeepSeek，否则用 BashListProvider（mock）
import os as _os
if _os.environ.get("DEEPSEEK_PROVIDER", "").lower() in ("1", "true", "yes"):
    from providers.deepseek import DeepSeekProvider
    _CURRENT_PROVIDER = DeepSeekProvider()
    print(f"[Provider] DeepSeekProvider (真实 API)")
else:
    _CURRENT_PROVIDER = BashListProvider()
    print(f"[Provider] BashListProvider (mock, DEEPSEEK_PROVIDER=true 切换到真实 API)")


# ── 启动 ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    cfg = config.load_config()
    port = cfg.get("port", 8080)

    print(f"=== DeepSeek Web Agent Proxy ===")
    print(f"Listening on http://127.0.0.1:{port}")
    print(f"Authenticated: {bool(cfg.get('token'))}")
    print(f"Session: {cfg.get('session_id', 'N/A')[:16]}...")
    print()
    print("Endpoints:")
    print(f"  POST /v1/chat/completions  →  OpenAI Chat API (需要审批)")
    print(f"  POST /login                →  Login to DeepSeek")
    print(f"  GET  /health               →  Health check")
    print(f"  GET  /api/pending           →  待审批列表")
    print(f"  POST /api/approve/{'{id}'}    →  放行请求")
    print(f"  POST /api/reject/{'{id}'}    →  拒绝请求")
    print()

    uvicorn.run(app, host="0.0.0.0", port=port)
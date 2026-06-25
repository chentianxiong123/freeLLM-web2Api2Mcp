"""DeepSeek Web Agent Proxy — 入口文件

将 DeepSeek 网页端免费对话转换为 OpenAI Chat Completions API，
供 Claude Code（OpenAI 模式）作为后端模型使用。
"""

import sys
import os
import json
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from debug_interceptor import interceptor
from backends.deepseek_web.login import login as ds_login
import accounts
import config
import session as sess

from routes.accounts import router as accounts_router
from routes.sessions import router as sessions_router
from routes.rules import router as rules_router
from routes.tools import router as tools_router
from routes.approval import router as approval_router
from routes.config_api import router as config_router
from routes.admin_pages import router as admin_router

app = FastAPI(
    title="DeepSeek Web Agent Proxy",
    version="0.4.0",
    description="DeepSeek 网页端 → OpenAI Chat Completions API 代理",
)

app.include_router(accounts_router)
app.include_router(sessions_router)
app.include_router(rules_router)
app.include_router(tools_router)
app.include_router(approval_router)
app.include_router(config_router)
app.include_router(admin_router)


# ── 调试拦截中间件 ──────────────────────────────────────


@app.middleware("http")
async def debug_middleware(request: Request, call_next):
    """捕获所有请求/响应用于调试。"""
    path = request.url.path
    # 跳过静态资源和 admin 页面
    if path.startswith("/admin") or path == "/":
        return await call_next(request)

    body = None
    try:
        body = await request.json()
    except Exception:
        pass

    # ── 落地原始 body 到 debug_requests/ ─────────────────
    if path == "/v1/chat/completions" and isinstance(body, dict):
        import os as _os_dl
        from datetime import datetime as _dt_dl
        _dl_dir = _os_dl.path.join(_os_dl.path.dirname(_os_dl.path.abspath(__file__)), "debug_requests")
        try:
            _os_dl.makedirs(_dl_dir, exist_ok=True)
        except OSError:
            pass
        _ts = _dt_dl.now().strftime("%Y%m%dT%H%M%S")
        _dl_name = f"{_ts}_{uuid.uuid4().hex[:6]}.json"
        try:
            with open(_os_dl.path.join(_dl_dir, _dl_name), "w", encoding="utf-8") as _f:
                json.dump({
                    "ts": _ts,
                    "path": path,
                    "headers": {k: v for k, v in request.headers.items() if k.lower() not in ("authorization", "cookie")},
                    "body": body,
                }, _f, ensure_ascii=False, indent=2)
            print(f"[DEBUG-DUMP] wrote {_dl_name} (body.messages={len(body.get('messages', []))})")
        except Exception as _e_dl:
            print(f"[DEBUG-DUMP] FAILED: {_e_dl}")

    rec = interceptor.start_request(
        method=request.method,
        path=path,
        body=body,
        headers=dict(request.headers),
    )

    try:
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        # SSE 流式响应 — 跳过 body 读取
        if "text/event-stream" in content_type:
            interceptor.finish_request(rec, status=response.status_code, body="<streaming>", headers=dict(response.headers))
            return response

        # 读取响应 body（只对 JSON 响应）
        resp_body = None
        if "application/json" in content_type:
            resp_body = b""
            async for chunk in response.body_iterator:
                resp_body += chunk if isinstance(chunk, bytes) else chunk.encode()
            try:
                parsed = json.loads(resp_body)
            except Exception:
                parsed = resp_body.decode()[:5000] if resp_body else None
            resp_body = parsed

            interceptor.finish_request(
                rec,
                status=response.status_code,
                body=resp_body,
                headers=dict(response.headers),
            )
            # 重建响应，否则 body_iterator 已被消费
            from starlette.responses import Response as StarletteResponse
            new_headers = {k: v for k, v in response.headers.items() if k.lower() not in ('content-length', 'content-type')}
            return StarletteResponse(
                content=resp_body if isinstance(resp_body, (str, bytes)) else json.dumps(resp_body, ensure_ascii=False),
                status_code=response.status_code,
                headers=new_headers,
                media_type="application/json",
            )

        interceptor.finish_request(
            rec,
            status=response.status_code,
            body=None,
            headers=dict(response.headers),
        )
        return response
    except Exception as e:
        interceptor.finish_request(rec, status=500, error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": {"type": "internal_server_error", "message": str(e)}},
        )


# ── 路由 ──────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI Chat Completions 端点。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={
            "error": {"message": "Invalid JSON", "type": "invalid_request_error"},
        })

    from pipeline.chat import run_chat_completion
    return await run_chat_completion(body=body, headers=dict(request.headers))


@app.get("/v1/models")
async def list_models():
    """返回可用模型列表（按当前 backend 过滤）。"""
    from config import load_config
    cfg = load_config()
    backend = cfg.get("backend", "deepseek")
    if backend == "qwen":
        models = [
            {"id": "qwen3.7-max", "object": "model", "created": 1700000000, "owned_by": "qwen"},
            {"id": "qwen3.0-plus", "object": "model", "created": 1700000000, "owned_by": "qwen"},
            {"id": "qwq-32b", "object": "model", "created": 1700000000, "owned_by": "qwen"},
        ]
    else:
        models = [
            {"id": "deepseek-v4-flash", "object": "model", "created": 1700000000, "owned_by": "deepseek"},
            {"id": "deepseek-v4-pro", "object": "model", "created": 1700000000, "owned_by": "deepseek"},
        ]
    return {"object": "list", "data": models}


@app.get("/health")
async def health():
    """健康检查"""
    from backends.registry import get_backend
    from agents.registry import list_agents, resolve_agent_id

    backend = get_backend()
    cfg = accounts.get_account_config()
    has_session = bool(cfg.get("session_id"))
    usage = sess.get_usage_status() if has_session else {}
    return {
        "status": "ok",
        "authenticated": backend.is_authenticated(),
        "session_active": has_session,
        "usage": usage,
        "backend_id": backend.id,
        "agents": list_agents(),
    }


@app.get("/api/meta/runtime")
async def api_meta_runtime():
    """当前 backend / 可选 agent 列表（运维用）。"""
    from backends.registry import list_backends, get_backend
    from agents.registry import list_agents
    import os
    return {
        "backend": get_backend().id,
        "backends": list_backends(),
        "agents": list_agents(),
        "env": {
            "WEB_BACKEND": os.environ.get("WEB_BACKEND", ""),
            "DOWNSTREAM_AGENT": os.environ.get("DOWNSTREAM_AGENT", ""),
        },
    }





@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin")


@app.post("/login")
async def login(request: Request):
    """登录 DeepSeek（兼容旧接口）。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    login_type = body.get("login_type", "email")
    password = body.get("password", "")
    account = body.get("account", "") or body.get("email", "") or body.get("mobile", "")
    if not account or not password:
        return JSONResponse(status_code=400, content={"ok": False, "error": "account and password required"})
    result = ds_login(login_type, account, password)
    if result:
        return {"ok": True, "message": "Login successful, session created"}
    else:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Login failed. Check console for details."})


# ── Backend 启动日志 ───────────────────────────────────────

import os as _os
from backends.registry import get_backend

_backend = get_backend()
if _os.environ.get("DEEPSEEK_PROVIDER", "").lower() in ("0", "false", "no"):
    print("[Backend] deepseek (DEEPSEEK_PROVIDER=0 → 未启用真实 API)")
else:
    print(f"[Backend] {_backend.id} ({_backend.display_name})")


# ── 启动 ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    import uvicorn.server

    # 尝试从旧版 config 导入账号
    accounts.import_from_config()

    cfg = config.load_config()
    port = cfg.get("port", 48391)

    print(f"=== DeepSeek Web Agent Proxy v0.4.0 ===")
    print(f"Listening on http://127.0.0.1:{port}")
    print()
    print("Endpoints:")
    print(f"  POST /v1/chat/completions  →  OpenAI Chat API")
    print(f"  GET  /admin                →  Admin Panel")
    print(f"  GET  /health               →  Health check")
    print()

    # 用 Server 类直接跑，不 spawn 子进程，避免残留孤儿进程
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        workers=1,
        reload=False,
        loop="asyncio",
        http="h11",
        log_config=None,
    )
    server = uvicorn.Server(config)
    server.run()

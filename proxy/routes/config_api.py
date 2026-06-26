from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import config

router = APIRouter(tags=["config"])


@router.get("/api/config/terminal")
async def api_get_terminal():
    return {"terminal": "powershell"}


@router.get("/api/config/model")
async def api_get_model():
    cfg = config.load_config()
    return {"model": cfg.get("model", "deepseek-v4-flash")}


@router.post("/api/config/model")
async def api_set_model(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    model = body.get("model", "deepseek-v4-flash")
    if model not in ("deepseek-v4-flash", "deepseek-v4-pro", "qwen3.7-max", "qwen3.0-plus", "qwq-32b"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "不支持的 model"})
    config.update_config(model=model)
    return {"ok": True, "model": model}


@router.get("/api/config/backend")
async def api_get_backend():
    cfg = config.load_config()
    return {"backend": cfg.get("backend", "deepseek")}


@router.post("/api/config/backend")
async def api_set_backend(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    backend = body.get("backend", "deepseek")
    if backend not in ("deepseek", "qwen"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "backend must be deepseek or qwen"})
    config.update_config(backend=backend)
    return {"ok": True, "backend": backend}


@router.get("/api/config/thinking")
async def api_get_thinking():
    cfg = config.load_config()
    return {"thinking_enabled": cfg.get("thinking_enabled", True)}


@router.post("/api/config/thinking")
async def api_set_thinking(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    enabled = body.get("thinking_enabled", True)
    if not isinstance(enabled, bool):
        return JSONResponse(status_code=400, content={"ok": False, "error": "thinking_enabled must be boolean"})
    config.update_config(thinking_enabled=enabled)
    return {"ok": True, "thinking_enabled": enabled}


@router.get("/api/config/token")
async def api_get_token():
    import accounts
    acc = accounts.get_active_account()
    if not acc:
        return {"token": "", "backend": ""}
    return {"token": acc.get("token", ""), "backend": acc.get("backend", ""), "session_id": acc.get("session_id", "")}


@router.post("/api/config/token")
async def api_set_token(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    token = body.get("token", "").strip()
    if not token:
        return JSONResponse(status_code=400, content={"ok": False, "error": "token 不能为空"})
    import accounts
    acc = accounts.get_active_account()
    if not acc:
        return JSONResponse(status_code=400, content={"ok": False, "error": "没有活跃账号"})
    accounts.update_account(acc["id"], {"token": token, "session_id": ""})
    # 清掉续接缓存
    try:
        from backends.qwen_web import qwen_api
        qwen_api.reset_last_message_id()
    except Exception:
        pass
    return {"ok": True, "message": "token 已更新，session 已重置"}

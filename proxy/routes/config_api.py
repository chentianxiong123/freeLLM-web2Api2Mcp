from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import config

router = APIRouter(tags=["config"])


@router.get("/api/config/terminal")
async def api_get_terminal():
    cfg = config.load_config()
    return {"terminal": cfg.get("terminal", "powershell")}


@router.post("/api/config/terminal")
async def api_set_terminal(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    terminal = body.get("terminal", "powershell")
    if terminal not in ("cmd", "powershell", "bash"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "terminal must be cmd/powershell/bash"})
    config.update_config(terminal=terminal)
    return {"ok": True, "terminal": terminal}


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

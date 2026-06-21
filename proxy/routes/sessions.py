from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import accounts
from backends.deepseek_web import deepseek_api as ds_api
import session as sess

router = APIRouter(tags=["sessions"])


@router.get("/api/sessions")
async def api_list_sessions():
    return {"sessions": sess.list_sessions()}


@router.post("/api/sessions/new")
async def api_new_session(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    label = body.get("label", "")
    model = body.get("model", "deepseek-v4-flash")

    cfg = accounts.get_account_config()
    if not cfg.get("token"):
        return JSONResponse(status_code=401, content={"ok": False, "error": "未登录"})

    new_sid = ds_api.create_new_session(cfg)
    if not new_sid:
        return JSONResponse(status_code=500, content={"ok": False, "error": "创建 session 失败"})

    sess.register_session(new_sid, label=label, model=model)
    sess.activate_session(new_sid)
    return {"ok": True, "session_id": new_sid, "label": label, "model": model}


@router.post("/api/sessions/activate")
async def api_activate_session(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    sid = body.get("session_id", "")
    if not sid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "session_id required"})
    ok = sess.activate_session(sid)
    return {"ok": ok, "session_id": sid if ok else None, "error": None if ok else "session 不存在"}


@router.post("/api/sessions/delete")
async def api_delete_session(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    sid = body.get("session_id", "")
    if not sid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "session_id required"})
    ok, err = sess.delete_session(sid)
    if not ok:
        return JSONResponse(status_code=400, content={"ok": False, "error": err})
    return {"ok": True, "session_id": sid}


@router.post("/api/sessions/import")
async def api_import_session(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    sid = body.get("session_id", "").strip()
    if not sid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "session_id required"})
    label = body.get("label", "").strip()
    last_mid = body.get("last_message_id")
    if last_mid not in (None, ""):
        try:
            last_mid = int(last_mid)
        except (ValueError, TypeError):
            return JSONResponse(status_code=400, content={"ok": False, "error": "last_message_id 必须是整数或留空"})
    else:
        last_mid = None
    activate = bool(body.get("activate", False))
    sess.register_session(sid, label=label)
    if last_mid is not None or body.get("clear_mid"):
        sess.set_specific_last_message_id(sid, last_mid)
    if activate:
        sess.activate_session(sid)
    return {"ok": True, "session_id": sid, "label": label, "last_message_id": last_mid, "activated": activate}


@router.post("/api/sessions/edit-mid")
async def api_edit_session_mid(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    sid = body.get("session_id", "").strip()
    last_mid = body.get("last_message_id")
    if not sid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "session_id required"})
    if last_mid in (None, ""):
        last_mid = None
    else:
        try:
            last_mid = int(last_mid)
        except (ValueError, TypeError):
            return JSONResponse(status_code=400, content={"ok": False, "error": "last_message_id 必须是整数或留空"})
    ok = sess.set_specific_last_message_id(sid, last_mid)
    if not ok:
        return JSONResponse(status_code=404, content={"ok": False, "error": "session 不存在"})
    return {"ok": True, "session_id": sid, "last_message_id": last_mid}

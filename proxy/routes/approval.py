from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import approval

router = APIRouter(tags=["approval"])


@router.get("/api/approval/pending")
async def api_approval_pending():
    return {"items": approval.queue.list_pending(), "enabled": approval.queue.enabled, "transparent": approval.queue.transparent}


@router.get("/api/approval/history")
async def api_approval_history(limit: int = 50):
    return {"items": approval.queue.list_history(limit)}


@router.post("/api/approval/toggle")
async def api_approval_toggle():
    approval.queue.set_enabled(not approval.queue.enabled)
    return {"ok": True, "enabled": approval.queue.enabled}


@router.post("/api/approval/transparent")
async def api_approval_transparent():
    approval.queue.set_transparent(not approval.queue.transparent)
    return {"ok": True, "transparent": approval.queue.transparent}


@router.post("/api/approval/approve/{item_id}")
async def api_approval_approve(item_id: int):
    ok = approval.queue.approve(item_id)
    return {"ok": ok}


@router.post("/api/approval/reject/{item_id}")
async def api_approval_reject(item_id: int):
    ok = approval.queue.reject(item_id, error="用户拒绝")
    return {"ok": ok}


@router.post("/api/approval/edit/{item_id}")
async def api_approval_edit(item_id: int, request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    edited_body = body.get("body")
    ok = approval.queue.edit_item(item_id, edited_body)
    if not ok:
        return JSONResponse(status_code=404, content={"ok": False, "error": "item 不存在"})
    return {"ok": True}


@router.post("/api/approval/approve-all")
async def api_approval_approve_all():
    count = approval.queue.approve_all()
    return {"ok": True, "count": count}


@router.post("/api/approval/clear")
async def api_approval_clear():
    approval.queue.clear_all()
    return {"ok": True}


@router.post("/api/debug/intercept/clear")
async def api_clear_intercept():
    approval.queue.clear_history()
    return {"ok": True}

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

import config
import session as sess

router = APIRouter(tags=["admin"])


@router.get("/admin")
async def admin():
    cfg = config.load_config()
    usage = sess.get_usage_status() if cfg.get("session_id") else {}
    from admin_page import render_overview
    return HTMLResponse(render_overview(cfg, usage))


@router.get("/admin/accounts")
async def admin_accounts():
    from admin_page import render_accounts
    return HTMLResponse(render_accounts())


@router.get("/admin/sessions")
async def admin_sessions():
    from admin_page import render_sessions
    return HTMLResponse(render_sessions())


@router.get("/admin/rules")
async def admin_rules():
    from admin_page import render_rules
    return HTMLResponse(render_rules())


@router.get("/admin/parser-flow")
async def admin_parser_flow():
    from admin_page import render_parser_flow
    return HTMLResponse(render_parser_flow())


@router.get("/admin/debug")
async def admin_debug():
    from admin_page import render_debug
    return HTMLResponse(render_debug())


@router.get("/admin/prompts")
async def admin_prompts():
    from admin_page import render_prompts
    return HTMLResponse(render_prompts())


@router.get("/api/prompts")
async def api_get_prompts():
    from prompts import manager
    return JSONResponse(content=manager.get_all_prompts())


@router.put("/api/prompts/{name}")
async def api_set_prompt(name: str, request: Request):
    from prompts import manager
    body = await request.json()
    content = body.get("content", "")
    manager.set_prompt(name, content)
    return JSONResponse(content={"ok": True, "name": name})

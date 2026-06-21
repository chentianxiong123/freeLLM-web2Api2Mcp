from fastapi import APIRouter
from fastapi.responses import HTMLResponse

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


@router.get("/admin/tools")
async def admin_tools():
    from admin_page import render_tools
    return HTMLResponse(render_tools())


@router.get("/admin/parser-flow")
async def admin_parser_flow():
    from admin_page import render_parser_flow
    return HTMLResponse(render_parser_flow())


@router.get("/admin/debug")
async def admin_debug():
    from admin_page import render_debug
    return HTMLResponse(render_debug())

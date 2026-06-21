from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import rules
import gateway

router = APIRouter(tags=["rules"])


@router.get("/api/rules")
async def api_list_rules():
    return {"rules": rules.list_rules()}


@router.post("/api/rules/reset")
async def api_reset_rules():
    new_rules = rules.reset_to_defaults()
    return {"ok": True, "rules": new_rules}


@router.post("/api/rules/add")
async def api_add_rule(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    new_rule = rules.add_rule(body)
    return {"ok": True, "rule": new_rule}


@router.post("/api/rules/update/{rule_id}")
async def api_update_rule(rule_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    updated = rules.update_rule(rule_id, body)
    if not updated:
        return JSONResponse(status_code=404, content={"ok": False, "error": "rule 不存在"})
    return {"ok": True, "rule": updated}


@router.post("/api/rules/delete/{rule_id}")
async def api_delete_rule(rule_id: str):
    ok = rules.delete_rule(rule_id)
    return {"ok": ok, "id": rule_id}


@router.post("/api/rules/toggle/{rule_id}")
async def api_toggle_rule(rule_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    updated = rules.toggle_rule(rule_id, body.get("enabled"))
    if not updated:
        return JSONResponse(status_code=404, content={"ok": False, "error": "rule 不存在"})
    return {"ok": True, "rule": updated}


@router.post("/api/rules/test")
async def api_test_rules(request: Request):
    try:
        req_body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})

    body = req_body.get("body")
    if not isinstance(body, dict):
        prompt = req_body.get("prompt", "")
        body = {"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": prompt}]}

    clean_prompt = ""
    try:
        clean_prompt = gateway.extract_clean_user_prompt(body)
    except Exception:
        pass

    blocked, hit_rule = rules.is_blocked(body, clean_prompt)
    hits = [hit_rule] if hit_rule else []

    return {
        "ok": True,
        "clean_prompt_len": len(clean_prompt),
        "clean_prompt_preview": clean_prompt[:200],
        "blocked": blocked,
        "first_hit": hit_rule,
        "hits": hits,
    }

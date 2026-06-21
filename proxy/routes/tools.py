from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import accounts
import config
from backends.deepseek_web import deepseek_api as ds_api
import session as sess
import tool_config

router = APIRouter(tags=["tools"])


@router.get("/api/tool-config")
async def api_get_tool_config():
    cfg = tool_config.get_config()
    return {"sections": cfg.get("sections", []), "tools": cfg.get("tools", {})}


@router.post("/api/tool-config")
async def api_save_tool_config(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    data = tool_config.update_config(body)
    sec_count = len(data.get("sections", []))
    return {"ok": True, "sections": sec_count, "tool_count": len(data.get("tools", {}))}


@router.post("/api/tool-config/reset-defaults")
async def api_tool_config_reset_defaults():
    data = tool_config.reset_to_defaults()
    return {"ok": True, "sections": len(data.get("sections", [])), "tools": len(data.get("tools", {}))}


@router.post("/api/tool-config/parse")
async def api_tool_config_parse(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})
    text = body.get("text", "")
    if not text:
        return JSONResponse({"error": "text required"})
    try:
        from tool_format import parse_tool_blocks
        remaining, tool_calls = parse_tool_blocks(text, None)
        return JSONResponse({"tool_calls": tool_calls, "remaining": remaining})
    except Exception as e:
        return JSONResponse({"error": str(e)})


@router.post("/api/tool-config/init")
async def api_init_tools(request: Request):
    cfg = accounts.get_account_config()
    if not cfg.get("token"):
        return JSONResponse(status_code=401, content={"ok": False, "error": "未登录"})
    active_sid = sess.get_current_session_id()
    if not active_sid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "没有 active session"})
    cfg["session_id"] = active_sid

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    working_directory = body.get("working_directory", "") or body.get("cwd", "")
    project_context = body.get("project_context", "")
    preview_only = body.get("preview", False)

    prompt = tool_config.build_init_prompt(working_directory=working_directory)

    if project_context:
        prompt += f"\n\n项目背景：{project_context}"

    print(f"[ToolInit] 发送初始化消息（{len(prompt)} 字符, wd={working_directory or '(默认)'}）")

    if preview_only:
        return {"ok": True, "prompt": prompt, "length": len(prompt)}

    ds_messages = [{"role": "user", "content": prompt}]
    active_model = sess.get_active_model()
    active_model_type = "expert" if "pro" in active_model else "default"
    ds_stream = ds_api.chat_completion(
        cfg=cfg, messages=ds_messages, model=active_model, model_type=active_model_type,
        thinking_enabled=True, search_enabled=False, stream=True,
    )

    full_content = ""
    got_message_id = None
    for etype, val in ds_stream:
        if etype == "content":
            full_content += val if isinstance(val, str) else ""
        elif etype == "message_id":
            got_message_id = val

    preview = (full_content[:100].replace('\n', ' ') + '…') if len(full_content) > 100 else full_content.replace('\n', ' ')
    if got_message_id:
        sess.set_last_message_id(got_message_id)
        sess.increment_message_count()

    return {"ok": True, "message": "初始化消息已发送", "response_preview": preview[:200], "message_id": got_message_id}

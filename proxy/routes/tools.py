from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import accounts
import config
from backends.registry import get_backend
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
    # 按当前 backend 选择解析器
    backend_id = config.load_config().get("backend", "deepseek")
    try:
        if backend_id == "qwen":
            # Qwen：尝试解析 JSON tool_calls
            import json as _json
            import re as _re
            tool_calls = []
            for match in _re.finditer(r'\{\s*"name"\s*:\s*"[^"]*"\s*,\s*"arguments"\s*:\s*\{[^}]*\}\s*\}', text):
                try:
                    tc = _json.loads(match.group())
                    tool_calls.append(tc)
                except _json.JSONDecodeError:
                    pass
            remaining = text
            return JSONResponse({"tool_calls": tool_calls, "remaining": remaining})
        else:
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

    print(f"[ToolInit] 初始化消息（{len(prompt)} 字符, wd={working_directory or '(默认)'}）")

    if preview_only:
        return {"ok": True, "prompt": prompt, "length": len(prompt)}

    # 通过当前 backend 发送
    backend = get_backend()
    provider = backend.get_provider()
    messages = [{"role": "user", "content": prompt}]
    active_model = backend.active_model()

    collected = []
    async for ev in provider.chat(
        messages, model=active_model,
        account_config=cfg,
        thinking_enabled=True, search_enabled=False,
    ):
        collected.append(ev)

    full_content = ""
    got_message_id = None
    for ev in collected:
        if ev.type == "content" and isinstance(ev.val, str):
            full_content += ev.val
        elif ev.type == "message_id":
            got_message_id = ev.val

    preview = (full_content[:100].replace('\n', ' ') + '…') if len(full_content) > 100 else full_content.replace('\n', ' ')

    # DeepSeek 特有：跟踪 message_id
    if got_message_id:
        sess.set_last_message_id(got_message_id)
        sess.increment_message_count()

    return {"ok": True, "message": "初始化消息已发送", "response_preview": preview[:200], "message_id": got_message_id}

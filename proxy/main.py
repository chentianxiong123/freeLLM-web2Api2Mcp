"""DeepSeek Web Agent Proxy — 入口文件

将 DeepSeek 网页端免费对话转换为 OpenAI Chat Completions API，
供 Claude Code（OpenAI 模式）作为后端模型使用。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import json
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse

from handler import stream_chat_to_sse, build_ds_input, collect_response, react_loop
import approval
from login import login as ds_login
from debug_interceptor import interceptor
import accounts
import config
import deepseek_api as ds_api
import session as sess
import gateway
import rules
import tool_config

app = FastAPI(
    title="DeepSeek Web Agent Proxy",
    version="0.3.0",
    description="DeepSeek 网页端 → OpenAI Chat Completions API 代理",
)


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

    rec = interceptor.start_request(
        method=request.method,
        path=path,
        body=body,
        headers=dict(request.headers),
    )

    try:
        response = await call_next(request)
        # 读取响应 body（只对 JSON 响应）
        resp_body = None
        if "application/json" in response.headers.get("content-type", ""):
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
    """OpenAI Chat Completions 端点。全部走非流式。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={
            "error": {"message": "Invalid JSON", "type": "invalid_request_error"},
        })

    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    model = body.get("model", "deepseek-v4-flash")
    tools = body.get("tools", []) or []

    # 调试：打印 body 结构
    msgs = body.get("messages", [])
    print(f"[chat_completions] model={model}, messages_count={len(msgs)}, tools_count={len(tools)}")
    for i, m in enumerate(msgs):
        role = m.get("role", "?")
        content = m.get("content", "")
        preview = content[:150].replace('\n', ' ') if isinstance(content, str) else str(content)[:150]
        print(f"[chat_completions]   [{i}] role={role}, content_preview={preview}")
        if role == "tool":
            print(f"[chat_completions]   >>> TOOL ROLE IN BODY <<<")

    # 预转换：提取用户消息
    chat_req = build_ds_input(body)

    # 审批：请求（含转换结果）
    req_result = await approval.queue.intercept_request(
        method="POST", path="/v1/chat/completions",
        body=body, headers=dict(request.headers),
        conversion={
            "user_content": chat_req.user_content[:5000] if chat_req.user_content else "",
            "is_react_continuation": chat_req.is_react_continuation,
            "tool_call_ids": chat_req.tool_call_ids,
            "messages_count": len(body.get("messages", [])),
        },
    )
    if req_result["action"] == "reject":
        return JSONResponse(status_code=403, content={
            "error": {"message": req_result.get("error", "请求被拒绝"), "type": "permission_error"},
        })

    # 获取当前活跃账号的 config
    cfg = accounts.get_account_config()
    if not cfg.get("token"):
        return JSONResponse(status_code=401, content={
            "error": {"message": "No active account", "type": "authentication_error"},
        })

    # 调用 Provider 收集完整响应（React 循环：本地执行 DS 的工具调用）
    t0 = time.time()

    # 使用编辑后的 user_content（如果有）
    final_user_content = chat_req.user_content
    working_directory = None
    if req_result.get("edited") and req_result.get("body"):
        edited = req_result["body"]
        if isinstance(edited, dict):
            if "user_content" in edited:
                final_user_content = edited["user_content"]
            if "working_directory" in edited:
                working_directory = edited["working_directory"]

    resp_body = await react_loop(
        _CURRENT_PROVIDER,
        final_user_content,
        request_id=request_id,
        model=model,
        tools_schema=tools,
        cwd=working_directory,
    )

    duration_ms = (time.time() - t0) * 1000

    # 审批：响应
    resp_result = await approval.queue.intercept_response(
        request_item_id=0, status=200,
        body=resp_body, duration_ms=duration_ms,
    )
    if resp_result["action"] == "reject":
        return JSONResponse(status_code=403, content={
            "error": {"message": resp_result.get("error", "响应被拒绝"), "type": "permission_error"},
        })

    # 使用编辑后的响应（如果有）
    final_resp = resp_body
    if resp_result.get("edited") and resp_result.get("body"):
        final_resp = resp_result["body"]

    return JSONResponse(content=final_resp)


@app.get("/v1/models")
async def list_models():
    """返回可用模型列表。"""
    return {"object": "list", "data": [
        {"id": "deepseek-v4-flash", "object": "model", "created": 1700000000, "owned_by": "deepseek"},
        {"id": "deepseek-v4-pro", "object": "model", "created": 1700000000, "owned_by": "deepseek"},
    ]}


@app.get("/health")
async def health():
    """健康检查"""
    cfg = accounts.get_account_config()
    has_session = bool(cfg.get("session_id"))
    usage = sess.get_usage_status() if has_session else {}
    return {
        "status": "ok",
        "authenticated": bool(cfg.get("token")),
        "session_active": has_session,
        "usage": usage,
    }


# ── 账号管理 API ──────────────────────────────────────


@app.get("/api/accounts")
async def api_list_accounts():
    """列出所有账号。"""
    return {"accounts": accounts.list_accounts()}


@app.post("/api/accounts/add")
async def api_add_account(request: Request):
    """添加账号并自动登录。body: {label, login_type, account, password}"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    new_acc = accounts.add_account(
        label=body.get("label", ""),
        login_type=body.get("login_type", "email"),
        account=body.get("account", ""),
        password=body.get("password", ""),
    )
    # 自动登录
    result = ds_login(new_acc["login_type"], body.get("account", ""), body.get("password", ""))
    if result and result.get("token"):
        accounts.save_account_token(
            new_acc["id"],
            token=result.get("token", ""),
            session_id=result.get("session_id", ""),
            headers=result.get("headers", {}),
        )
        return {"ok": True, "account": new_acc, "logged_in": True}
    return {"ok": True, "account": new_acc, "logged_in": False, "message": "已添加但登录失败，请手动登录"}


@app.post("/api/accounts/delete/{acc_id}")
async def api_delete_account(acc_id: str):
    """删除账号。"""
    ok = accounts.delete_account(acc_id)
    return {"ok": ok, "id": acc_id}


@app.post("/api/accounts/activate/{acc_id}")
async def api_activate_account(acc_id: str):
    """切换活跃账号。"""
    ok = accounts.activate_account(acc_id)
    if ok:
        # 同步更新 session.py 的 active session
        acc = accounts.get_active_account()
        if acc and acc.get("session_id"):
            sess.activate_session(acc["session_id"])
    return {"ok": ok, "id": acc_id}


@app.post("/api/accounts/login/{acc_id}")
async def api_login_account(acc_id: str, request: Request):
    """登录指定账号。"""
    accs = accounts._load()
    target = None
    for acc in accs:
        if acc.get("id") == acc_id:
            target = acc
            break
    if not target:
        return JSONResponse(status_code=404, content={"ok": False, "error": "账号不存在"})

    result = ds_login(target["login_type"], target["account"], target["password"])
    if result and result.get("token"):
        accounts.save_account_token(
            acc_id,
            token=result.get("token", ""),
            session_id=result.get("session_id", ""),
            headers=result.get("headers", {}),
        )
        return {"ok": True, "message": "登录成功"}
    return JSONResponse(status_code=401, content={"ok": False, "error": "登录失败"})


@app.post("/api/accounts/import")
async def api_import_account():
    """从旧版 config.json 导入账号。"""
    ok = accounts.import_from_config()
    return {"ok": ok, "message": "已导入" if ok else "无需导入（已存在或无数据）"}


# ── 违规拦截规则 API ──────────────────────────────


@app.get("/api/rules")
async def api_list_rules():
    """列出所有拦截规则。"""
    return {"rules": rules.list_rules()}


@app.post("/api/rules/reset")
async def api_reset_rules():
    """重置为默认规则集。"""
    new_rules = rules.reset_to_defaults()
    return {"ok": True, "rules": new_rules}


@app.post("/api/rules/add")
async def api_add_rule(request: Request):
    """新增规则。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    new_rule = rules.add_rule(body)
    return {"ok": True, "rule": new_rule}


@app.post("/api/rules/update/{rule_id}")
async def api_update_rule(rule_id: str, request: Request):
    """更新规则。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    updated = rules.update_rule(rule_id, body)
    if not updated:
        return JSONResponse(status_code=404, content={"ok": False, "error": "rule 不存在"})
    return {"ok": True, "rule": updated}


@app.post("/api/rules/delete/{rule_id}")
async def api_delete_rule(rule_id: str):
    """删除规则。"""
    ok = rules.delete_rule(rule_id)
    return {"ok": ok, "id": rule_id}


@app.post("/api/rules/toggle/{rule_id}")
async def api_toggle_rule(rule_id: str, request: Request):
    """切换 enabled。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    updated = rules.toggle_rule(rule_id, body.get("enabled"))
    if not updated:
        return JSONResponse(status_code=404, content={"ok": False, "error": "rule 不存在"})
    return {"ok": True, "rule": updated}


@app.post("/api/rules/test")
async def api_test_rules(request: Request):
    """测试规则命中。"""
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


# ── 工具调用配置 API ──────────────────────────────


@app.get("/api/tool-config")
async def api_get_tool_config():
    """获取工具定义列表 + 环节配置。"""
    cfg = tool_config.get_config()
    return {"sections": cfg.get("sections", []), "tools": cfg.get("tools", {})}


@app.post("/api/tool-config")
async def api_save_tool_config(request: Request):
    """保存工具定义和环节。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    data = tool_config.update_config(body)
    sec_count = len(data.get("sections", []))
    return {"ok": True, "sections": sec_count, "tool_count": len(data.get("tools", {}))}


@app.get("/api/config/terminal")
async def api_get_terminal():
    """获取当前终端类型。"""
    cfg = config.load_config()
    return {"terminal": cfg.get("terminal", "powershell")}


@app.post("/api/config/terminal")
async def api_set_terminal(request: Request):
    """设置终端类型。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    terminal = body.get("terminal", "powershell")
    if terminal not in ("cmd", "powershell", "bash"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "terminal must be cmd/powershell/bash"})
    config.update_config(terminal=terminal)
    return {"ok": True, "terminal": terminal}


@app.post("/api/tool-config/init")
async def api_init_tools(request: Request):
    """发送初始化消息给 DeepSeek。携带工作目录、项目背景。"""
    cfg = accounts.get_account_config()
    if not cfg.get("token"):
        return JSONResponse(status_code=401, content={"ok": False, "error": "未登录"})
    if not cfg.get("session_id"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "没有 active session"})

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    working_directory = body.get("working_directory", "") or body.get("cwd", "")
    project_context = body.get("project_context", "")
    preview_only = body.get("preview", False)

    prompt = tool_config.build_init_prompt(working_directory=working_directory)

    # 项目背景追加
    if project_context:
        prompt += f"\n\n项目背景：{project_context}"

    print(f"[ToolInit] 发送初始化消息（{len(prompt)} 字符, wd={working_directory or '(默认)'}）")

    # 预览模式：只返回不发送
    if preview_only:
        return {"ok": True, "prompt": prompt, "length": len(prompt)}

    ds_messages = [{"role": "user", "content": prompt}]
    ds_stream = ds_api.chat_completion(
        cfg=cfg, messages=ds_messages, model="deepseek-default", model_type="default",
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


# ── Session 管理 API ──────────────────────────────────────


@app.get("/api/sessions")
async def api_list_sessions():
    """列出所有 session。"""
    return {"sessions": sess.list_sessions()}


@app.post("/api/sessions/new")
async def api_new_session(request: Request):
    """新建 session。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    label = body.get("label", "")

    cfg = accounts.get_account_config()
    if not cfg.get("token"):
        return JSONResponse(status_code=401, content={"ok": False, "error": "未登录"})

    new_sid = ds_api.create_new_session(cfg)
    if not new_sid:
        return JSONResponse(status_code=500, content={"ok": False, "error": "创建 session 失败"})

    sess.register_session(new_sid, label=label)
    sess.activate_session(new_sid)
    return {"ok": True, "session_id": new_sid, "label": label}


@app.post("/api/sessions/activate")
async def api_activate_session(request: Request):
    """切换 active session。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    sid = body.get("session_id", "")
    if not sid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "session_id required"})
    ok = sess.activate_session(sid)
    return {"ok": ok, "session_id": sid if ok else None, "error": None if ok else "session 不存在"}


@app.post("/api/sessions/delete")
async def api_delete_session(request: Request):
    """删除 session。"""
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


@app.post("/api/sessions/import")
async def api_import_session(request: Request):
    """手动导入 session。"""
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


@app.post("/api/sessions/edit-mid")
async def api_edit_session_mid(request: Request):
    """编辑 session 续接点。"""
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


# ── 审批 API ──────────────────────────────────────


@app.get("/api/approval/pending")
async def api_approval_pending():
    """列出待审批项。"""
    return {"items": approval.queue.list_pending(), "enabled": approval.queue.enabled, "transparent": approval.queue.transparent}


@app.get("/api/approval/history")
async def api_approval_history(limit: int = 50):
    """列出已审批历史。"""
    return {"items": approval.queue.list_history(limit)}


@app.post("/api/approval/toggle")
async def api_approval_toggle():
    """开启/关闭审批拦截。"""
    approval.queue.set_enabled(not approval.queue.enabled)
    return {"ok": True, "enabled": approval.queue.enabled}


@app.post("/api/approval/transparent")
async def api_approval_transparent():
    """开启/关闭透明拦截模式（直接放行但留痕）。"""
    approval.queue.set_transparent(not approval.queue.transparent)
    return {"ok": True, "transparent": approval.queue.transparent}


@app.post("/api/approval/approve/{item_id}")
async def api_approval_approve(item_id: int):
    """放行指定项。"""
    ok = approval.queue.approve(item_id)
    return {"ok": ok}


@app.post("/api/approval/reject/{item_id}")
async def api_approval_reject(item_id: int):
    """拒绝指定项。"""
    ok = approval.queue.reject(item_id, error="用户拒绝")
    return {"ok": ok}


@app.post("/api/approval/edit/{item_id}")
async def api_approval_edit(item_id: int, request: Request):
    """编辑待审批项的 body。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    edited_body = body.get("body")
    ok = approval.queue.edit_item(item_id, edited_body)
    if not ok:
        return JSONResponse(status_code=404, content={"ok": False, "error": "item 不存在"})
    return {"ok": True}


@app.post("/api/approval/approve-all")
async def api_approval_approve_all():
    """放行所有。"""
    count = approval.queue.approve_all()
    return {"ok": True, "count": count}


@app.post("/api/approval/clear")
async def api_approval_clear():
    """清空所有。"""
    approval.queue.clear_all()
    return {"ok": True}


@app.post("/api/debug/intercept/clear")
async def api_clear_intercept():
    """清空拦截记录。"""
    approval.queue.clear_history()
    return {"ok": True}


# ── 管理页面 ──────────────────────────────────────────


@app.get("/admin")
async def admin():
    """概览页。"""
    cfg = config.load_config()
    usage = sess.get_usage_status() if cfg.get("session_id") else {}
    from admin_page import render_overview
    return HTMLResponse(render_overview(cfg, usage))


@app.get("/admin/accounts")
async def admin_accounts():
    """账号管理页。"""
    from admin_page import render_accounts
    return HTMLResponse(render_accounts())


@app.get("/admin/sessions")
async def admin_sessions():
    """会话管理页。"""
    from admin_page import render_sessions
    return HTMLResponse(render_sessions())


@app.get("/admin/rules")
async def admin_rules():
    """规则管理页。"""
    from admin_page import render_rules
    return HTMLResponse(render_rules())


@app.get("/admin/tools")
async def admin_tools():
    """工具配置页。"""
    from admin_page import render_tools
    return HTMLResponse(render_tools())


@app.get("/admin/debug")
async def admin_debug():
    """调试拦截页。"""
    from admin_page import render_debug
    return HTMLResponse(render_debug())


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


# ── Provider 初始化 ───────────────────────────────


import os as _os
if _os.environ.get("DEEPSEEK_PROVIDER", "").lower() in ("0", "false", "no"):
    from providers.base import Event
    from typing import AsyncIterator

    class BashListProvider:
        """Mock provider for testing."""
        async def chat(self, messages: list[dict], **kwargs) -> AsyncIterator[Event]:
            yield Event(type="content", val="Hello! I'm a mock provider. ")
            yield Event(type="content", val="Set DEEPSEEK_PROVIDER=true to use the real API.")
            yield Event(type="done", val=None)

    _CURRENT_PROVIDER = BashListProvider()
    print(f"[Provider] BashListProvider (mock)")
else:
    from providers.deepseek import DeepSeekProvider
    _CURRENT_PROVIDER = DeepSeekProvider()
    print(f"[Provider] DeepSeekProvider (真实 API)")


# ── 启动 ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    # 尝试从旧版 config 导入账号
    accounts.import_from_config()

    cfg = config.load_config()
    port = cfg.get("port", 48391)

    print(f"=== DeepSeek Web Agent Proxy v0.3.0 ===")
    print(f"Listening on http://127.0.0.1:{port}")
    print()
    print("Endpoints:")
    print(f"  POST /v1/chat/completions  →  OpenAI Chat API")
    print(f"  GET  /admin                →  Admin Panel")
    print(f"  GET  /health               →  Health check")
    print()

    uvicorn.run(app, host="0.0.0.0", port=port)

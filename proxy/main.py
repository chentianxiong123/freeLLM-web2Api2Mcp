"""DeepSeek Web Agent Proxy — 入口文件

将 DeepSeek 网页端免费对话转换为 OpenAI Chat Completions API，
供 Claude Code（OpenAI 模式）作为后端模型使用。

特点：
- 单会话持久化，不新建
- 增量消息传递，依赖服务端上下文
- 网关审批：所有请求先挂起，管理员确认后才发送
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import json
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse

from anthropic_handler import handle_chat
import config
import deepseek_api as ds_api
import session as sess
import gateway

app = FastAPI(
    title="DeepSeek Web Agent Proxy",
    version="0.1.0",
    description="DeepSeek 网页端 → OpenAI Chat Completions API 代理",
)


# ── 错误处理中间件 ──────────────────────────────────────


@app.middleware("http")
async def error_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "type": "internal_server_error",
                    "message": str(e),
                },
            },
        )


# ── 路由 ──────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Chat Completions API 端点（走网关审批）"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={
            "error": {"message": "Invalid JSON", "type": "invalid_request_error"},
        })

    # 提取用户消息摘要
    msgs = body.get("messages", [])
    user_preview = ""
    is_tool_result = False
    for msg in reversed(msgs):
        if msg.get("role") == "user":
            c = msg.get("content", "")
            if isinstance(c, list):
                texts = []
                for b in c:
                    if isinstance(b, dict):
                        if b.get("type") == "text":
                            texts.append(b.get("text", ""))
                        elif b.get("type") == "tool_result":
                            is_tool_result = True
                user_preview = " ".join(texts)[:200]
            else:
                user_preview = str(c)[:200]
            break

    if is_tool_result:
        # 工具结果回传，自动放行
        return await handle_chat(request)
    else:
        # ✅ 当前模式：直通（暂不审批，所有请求自动放行）
        # TODO: 之后可恢复审批模式（管理员手动放行）
        return await handle_chat(request)


@app.get("/v1/models")
async def list_models():
    """返回可用模型列表（OpenAI 格式）"""
    models_data = [
        {"id": "deepseek-v4-flash", "object": "model", "created": 1700000000, "owned_by": "deepseek"},
        {"id": "deepseek-v4-pro", "object": "model", "created": 1700000000, "owned_by": "deepseek"},
    ]
    return {"object": "list", "data": models_data}


@app.get("/health")
async def health():
    """健康检查"""
    cfg = config.load_config()
    has_session = bool(cfg.get("session_id"))
    usage = sess.get_usage_status() if has_session else {}
    return {
        "status": "ok",
        "authenticated": bool(cfg.get("token")),
        "session_active": has_session,
        "usage": usage,
    }


# ── 审批 API ──────────────────────────────────────────


@app.get("/api/pending")
async def api_pending():
    """获取待审批请求列表"""
    return {"requests": gateway.get_pending_list()}


@app.get("/api/request/{req_id}")
async def api_request_detail(req_id: str):
    """获取单个请求的完整详情"""
    detail = gateway.get_request_detail(req_id)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return detail


@app.post("/api/approve/{req_id}")
async def api_approve(req_id: str):
    """放行请求"""
    ok = gateway.approve(req_id)
    return {"ok": ok, "id": req_id}


@app.post("/api/reject/{req_id}")
async def api_reject(req_id: str):
    """拒绝请求"""
    ok = gateway.reject(req_id)
    return {"ok": ok, "id": req_id}


# ── 测试触发器（调试用） ──────────────────────────────────────


@app.post("/api/test/mock")
async def api_test_mock(request: Request):
    """测试触发器：直接构造一个最小化的 OpenAI 请求走 mock 路径。

    用法：POST /api/test/mock，body 里可带 {"stream": true/false, "prompt": "你好"}
    默认 prompt = "你好"，stream = true。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    prompt = body.get("prompt", "你好")
    is_stream = bool(body.get("stream", True))
    model = body.get("model", "deepseek-v4-flash")

    fake_body = {
        "model": model,
        "stream": is_stream,
        "messages": [{"role": "user", "content": prompt}],
    }

    # 直接调用 chat_completions 让它走和 Claude Code 一样的分支
    fake_request = Request(scope={"type": "http", "method": "POST", "headers": []})
    fake_request._body = json.dumps(fake_body).encode("utf-8")
    return await chat_completions(fake_request)


# ── Session 管理 API ──────────────────────────────────────


@app.get("/api/sessions")
async def api_list_sessions():
    """列出所有 session（含 active 标记 + message_count / last_used）。"""
    return {"sessions": sess.list_sessions()}


@app.post("/api/sessions/new")
async def api_new_session(request: Request):
    """新建 session（调 DeepSeek /chat_session/create，注册到列表并激活）。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    label = body.get("label", "")

    cfg = config.load_config()
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
    """切换 active session（写 sessions.json + config.json，下次请求走新 session）。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})

    sid = body.get("session_id", "")
    if not sid:
        return JSONResponse(status_code=400, content={"ok": False, "error": "session_id required"})

    ok = sess.activate_session(sid)
    return {"ok": ok, "session_id": sid if ok else None, "error": None if ok else "session 不存在"}


# ── 管理页面 ──────────────────────────────────────────


@app.get("/admin")
async def admin():
    """管理控制台页面。"""
    cfg = config.load_config()
    usage = sess.get_usage_status() if cfg.get("session_id") else {}

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DeepSeek Proxy 管理</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f0f2f5; padding:20px; color:#333; }}
.container {{ max-width:900px; margin:0 auto; }}
.card {{ background:#fff; border-radius:12px; padding:20px; margin-bottom:16px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
h1 {{ font-size:22px; margin-bottom:6px; }}
.subtitle {{ font-size:13px; color:#888; margin-bottom:16px; }}
h2 {{ font-size:15px; color:#333; margin-bottom:12px; font-weight:600; }}
label {{ display:block; font-size:13px; font-weight:600; margin:10px 0 4px; }}
input, select {{ width:100%; padding:10px; border:1px solid #ddd; border-radius:8px; font-size:14px; font-family:inherit; }}
button {{ padding:8px 14px; border:none; border-radius:6px; font-size:13px; cursor:pointer; font-family:inherit; transition:opacity .15s; }}
button:hover {{ opacity:.8; }}
button:disabled {{ opacity:.5; cursor:not-allowed; }}
.btn-primary {{ background:#1677ff; color:#fff; width:100%; padding:12px; font-size:15px; margin-top:12px; }}
.btn-approve {{ background:#52c41a; color:#fff; }}
.btn-reject {{ background:#ff4d4f; color:#fff; }}
.btn-ghost {{ background:#f5f5f5; color:#666; border:1px solid #d9d9d9; }}
.btn-toggle {{ background:#fff; color:#1677ff; border:1px solid #1677ff; padding:4px 10px; font-size:12px; }}
.status-item {{ display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid #f0f0f0; font-size:14px; }}
.status-item:last-child {{ border:none; }}
.status-item .label {{ color:#666; }}
.status-item .value {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:13px; }}
.tag {{ padding:2px 8px; border-radius:4px; font-size:12px; font-weight:500; }}
.tag-ok {{ background:#e6fffb; color:#006d75; }}
.tag-fail {{ background:#fff2f0; color:#a8071a; }}
.tag-warn {{ background:#fff7e6; color:#d46b08; }}
.msg {{ margin-top:12px; padding:10px 12px; border-radius:8px; font-size:13px; }}
.msg-ok {{ background:#f6ffed; color:#389e0d; border:1px solid #b7eb8f; }}
.msg-err {{ background:#fff2f0; color:#cf1322; border:1px solid #ffa39e; }}

/* 请求列表 */
.req-card {{ border:1px solid #e8e8e8; border-radius:10px; margin-bottom:10px; background:#fafafa; overflow:hidden; }}
.req-head {{ display:flex; align-items:center; gap:12px; padding:12px 14px; }}
.req-info {{ flex:1; min-width:0; }}
.req-preview {{ font-size:13px; color:#222; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-bottom:4px; }}
.req-preview:empty::before {{ content:'(空)'; color:#bbb; }}
.req-meta {{ font-size:11px; color:#999; display:flex; flex-wrap:wrap; gap:8px; }}
.req-meta b {{ color:#555; font-weight:600; }}
.req-actions {{ display:flex; gap:6px; flex-shrink:0; }}

/* 折叠详情 */
.req-body {{ background:#fff; border-top:1px solid #e8e8e8; padding:14px; display:none; }}
.req-body.open {{ display:block; }}
.section {{ margin-bottom:14px; }}
.section:last-child {{ margin-bottom:0; }}
.section-title {{ font-size:12px; font-weight:600; color:#888; text-transform:uppercase; letter-spacing:.5px; margin-bottom:6px; display:flex; align-items:center; gap:8px; }}
.section-title .badge {{ background:#f0f0f0; color:#555; padding:1px 6px; border-radius:3px; font-size:11px; font-weight:500; text-transform:none; letter-spacing:0; }}

/* 系统提示词特殊高亮 */
.sys-info {{ background:#fff7e6; border:1px solid #ffd591; border-radius:6px; padding:8px 10px; font-size:12px; color:#874d00; margin-bottom:8px; }}
.sys-info b {{ color:#d46b08; }}

/* 消息块 */
.msg-block {{ border-left:3px solid #d9d9d9; padding:8px 10px; margin-bottom:6px; background:#fafafa; border-radius:0 6px 6px 0; }}
.msg-block.user {{ border-left-color:#1677ff; }}
.msg-block.assistant {{ border-left-color:#52c41a; }}
.msg-block.tool {{ border-left-color:#fa8c16; }}
.msg-block.system {{ border-left-color:#722ed1; }}
.msg-head {{ font-size:11px; color:#888; margin-bottom:4px; display:flex; gap:6px; align-items:center; }}
.msg-head .role {{ font-weight:600; color:#333; }}
.msg-head .idx {{ background:#f0f0f0; padding:0 6px; border-radius:3px; font-size:10px; }}
.msg-text {{ font-size:13px; line-height:1.6; white-space:pre-wrap; word-break:break-word; color:#222; }}
.msg-text.empty {{ color:#bbb; font-style:italic; }}
.tool-tag {{ display:inline-block; padding:1px 6px; border-radius:3px; font-size:11px; font-weight:600; margin-right:4px; }}
.tool-tag.use {{ background:#fff7e6; color:#d46b08; }}
.tool-tag.result {{ background:#e6f7ff; color:#0958d9; }}
.tool-tag.thinking {{ background:#f9f0ff; color:#531dab; }}
.tool-tag.text {{ background:#f6ffed; color:#389e0d; }}

/* 提示词预览框 */
.code-box {{ background:#1e1e1e; color:#d4d4d4; padding:10px 12px; border-radius:6px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; line-height:1.55; max-height:300px; overflow:auto; white-space:pre-wrap; word-break:break-word; }}
.code-box .dim {{ color:#888; }}

/* 加载/空态 */
.empty {{ text-align:center; color:#ccc; padding:30px; font-size:14px; }}
.spinner {{ display:inline-block; width:12px; height:12px; border:2px solid #d9d9d9; border-top-color:#1677ff; border-radius:50%; animation:spin .8s linear infinite; margin-right:6px; vertical-align:middle; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}

/* 模态弹窗 */
.modal-mask {{ position:fixed; inset:0; background:rgba(0,0,0,.45); display:none; align-items:center; justify-content:center; z-index:1000; padding:20px; }}
.modal-mask.open {{ display:flex; }}
.modal {{ background:#fff; border-radius:12px; width:100%; max-width:860px; max-height:90vh; display:flex; flex-direction:column; box-shadow:0 10px 40px rgba(0,0,0,.2); }}
.modal-head {{ padding:16px 20px; border-bottom:1px solid #eee; display:flex; justify-content:space-between; align-items:center; flex-shrink:0; }}
.modal-head h3 {{ font-size:16px; font-weight:600; color:#222; }}
.modal-head .meta {{ font-size:12px; color:#888; margin-top:2px; }}
.modal-close {{ background:transparent; color:#888; font-size:22px; line-height:1; padding:4px 10px; }}
.modal-body {{ padding:20px; overflow-y:auto; flex:1; }}
.modal-foot {{ padding:12px 20px; border-top:1px solid #eee; display:flex; justify-content:flex-end; gap:8px; flex-shrink:0; }}

/* 顶部工具条 */
.toolbar {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }}
.toolbar .left {{ font-size:13px; color:#666; }}
.toolbar .right {{ display:flex; gap:8px; }}
</style>
</head>
<body>
<div class="container">
<h1>🔌 DeepSeek Proxy</h1>
<div class="subtitle">DeepSeek 网页端 → OpenAI Chat Completions 反向代理 · 管理员审批控制台</div>

<div class="card">
<h2>📊 状态</h2>
<div class="status-item"><span class="label">登录状态</span><span class="tag {'tag-ok' if cfg.get('token') else 'tag-fail'}">{'✅ 已登录' if cfg.get('token') else '❌ 未登录'}</span></div>
<div class="status-item"><span class="label">Token</span><span class="value">{(cfg.get('token','')[:24]+'…') if cfg.get('token') else '空'}</span></div>
<div class="status-item"><span class="label">会话 ID</span><span class="value">{(cfg.get('session_id','')[:24]+'…') if cfg.get('session_id') else '空'}</span></div>
<div class="status-item"><span class="label">本 session 累计 token</span><span class="value">{usage.get('prompt_tokens',0)}</span></div>
<div class="status-item"><span class="label">监听端口</span><span class="value">{cfg.get('port',8080)}</span></div>
</div>

<div class="card">
<div class="toolbar">
<h2 style="margin:0">💬 会话列表 <span id="sessionCount" style="font-size:12px;color:#999;font-weight:400"></span></h2>
<div class="right">
<button class="btn-ghost" onclick="refreshSessions()">🔄 刷新</button>
<button class="btn-primary" style="width:auto;padding:8px 14px;margin:0;font-size:13px" onclick="newSession()">➕ 新建会话</button>
</div>
</div>
<div id="sessionList"><div class="empty">点击右上"刷新"加载</div></div>
</div>

<div class="card">
<div class="toolbar">
<h2 style="margin:0">📥 待审批请求 <span id="pendingCount" style="font-size:12px;color:#999;font-weight:400"></span></h2>
<div class="right">
<button class="btn-ghost" onclick="refreshPending()">🔄 刷新列表</button>
</div>
</div>
<div id="reqList"><div class="empty">点击右上"刷新列表"加载</div></div>
</div>

<!-- 详情模态弹窗 -->
<div class="modal-mask" id="modal" onclick="if(event.target===this) closeModal()">
  <div class="modal">
    <div class="modal-head">
      <div>
        <h3 id="modalTitle">请求详情</h3>
        <div class="meta" id="modalMeta"></div>
      </div>
      <button class="modal-close" onclick="closeModal()">×</button>
    </div>
    <div class="modal-body" id="modalBody">
      <div class="loading" style="text-align:center;color:#999;padding:30px;font-size:13px"><span class="spinner"></span>正在加载详情…</div>
    </div>
    <div class="modal-foot" id="modalFoot">
      <button class="btn-ghost" onclick="closeModal()">关闭</button>
    </div>
  </div>
</div>

<div class="card">
<h2>📱 登录 DeepSeek</h2>
<form id="loginForm">
<label>登录方式</label>
<select id="loginType"><option value="email">邮箱</option><option value="phone">手机号</option></select>
<label>账号</label><input id="account" placeholder="邮箱或手机号">
<label>密码</label><input id="password" type="password" placeholder="密码">
<button class="btn-primary" id="loginBtn" onclick="doLogin()">登录</button>
</form>
<div id="loginMsg"></div>
</div>

</div>

<script>
const $ = id => document.getElementById(id);

function escapeHtml(s) {{
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);
}}

/* ── Session 管理 ────────────────────────────────── */

async function refreshSessions() {{
    const btn = document.querySelector('button[onclick="refreshSessions()"]');
    if (btn) {{ btn.disabled = true; btn.textContent = '🔄 刷新中…'; }}
    try {{
        const r = await fetch('/api/sessions');
        const d = await r.json();
        const list = $('sessionList');
        const ss = d.sessions || [];
        $('sessionCount').textContent = ss.length ? `(共 ${{ss.length}} 个)` : '';
        if (ss.length === 0) {{
            list.innerHTML = '<div class="empty">还没有 session，点右上"新建会话"创建</div>';
            return;
        }}
        list.innerHTML = ss.map(s => renderSessionCard(s)).join('');
    }} catch(e) {{
        $('sessionList').innerHTML = '<div class="empty">刷新失败: ' + escapeHtml(e.message) + '</div>';
    }} finally {{
        if (btn) {{ btn.disabled = false; btn.textContent = '🔄 刷新'; }}
    }}
}}

function renderSessionCard(s) {{
    const isActive = s.active;
    const activeBadge = isActive ? '<span class="tag tag-ok">🟢 当前活跃</span>' : '';
    const lastMid = s.last_message_id ? `parent_message_id=${{s.last_message_id}}` : '无（根消息）';
    const lastUsed = s.last_used_at ? new Date(s.last_used_at * 1000).toLocaleString('zh-CN') : '-';
    const created = s.created_at ? new Date(s.created_at * 1000).toLocaleString('zh-CN') : '-';
    const label = s.label ? `${{escapeHtml(s.label)}} · ` : '';
    const sidShort = s.session_id ? `${{s.session_id.slice(0, 8)}}…${{s.session_id.slice(-4)}}` : '-';
    const switchBtn = isActive
        ? '<button class="btn-toggle" disabled>已激活</button>'
        : `<button class="btn-approve" onclick="activateSession('${{s.session_id}}')">切换为此</button>`;
    return `
        <div class="req-card" style="${{isActive ? 'border-color:#52c41a;background:#f6ffed' : ''}}">
            <div class="req-head">
                <div class="req-info">
                    <div class="req-preview">${{label}}${{escapeHtml(sidShort)}} ${{activeBadge}}</div>
                    <div class="req-meta">
                        <b>消息数:</b> ${{s.message_count || 0}} 条
                        <span>·</span>
                        <b>累计 token:</b> ${{s.prompt_tokens || 0}}
                        <span>·</span>
                        <b>续接:</b> ${{escapeHtml(lastMid)}}
                        <span>·</span>
                        <b>创建:</b> ${{escapeHtml(created)}}
                        <span>·</span>
                        <b>最后使用:</b> ${{escapeHtml(lastUsed)}}
                    </div>
                </div>
                <div class="req-actions">
                    ${{switchBtn}}
                </div>
            </div>
        </div>
    `;
}}

async function newSession() {{
    const label = prompt('给新会话起个名字（可选）', '');
    if (label === null) return;  // 取消
    const btn = document.querySelector('button[onclick="newSession()"]');
    if (btn) {{ btn.disabled = true; btn.textContent = '⏳ 创建中…'; }}
    try {{
        const r = await fetch('/api/sessions/new', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{label: label}}),
        }});
        const d = await r.json();
        if (d.ok) {{
            showMsg('loginMsg', '✅ 新会话已创建并激活：' + d.session_id.slice(0, 8) + '…', true);
            refreshSessions();
        }} else {{
            showMsg('loginMsg', '❌ ' + (d.error || '创建失败'), false);
        }}
    }} catch(e) {{
        showMsg('loginMsg', '❌ ' + e.message, false);
    }} finally {{
        if (btn) {{ btn.disabled = false; btn.textContent = '➕ 新建会话'; }}
    }}
}}

async function activateSession(sid) {{
    if (!confirm('切换到 session ' + sid.slice(0, 8) + '…？\\n\\n下次 Claude Code 发消息会走这个 session。')) return;
    try {{
        const r = await fetch('/api/sessions/activate', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{session_id: sid}}),
        }});
        const d = await r.json();
        if (d.ok) {{
            showMsg('loginMsg', '✅ 已切换到 ' + sid.slice(0, 8) + '…', true);
            refreshSessions();
        }} else {{
            showMsg('loginMsg', '❌ ' + (d.error || '切换失败'), false);
        }}
    }} catch(e) {{
        showMsg('loginMsg', '❌ ' + e.message, false);
    }}
}}

/* ── 列表刷新（手动） ─────────────────────────────── */

let _refreshing = false;

async function refreshPending() {{
    if (_refreshing) return;
    _refreshing = true;
    const btn = document.querySelector('button[onclick="refreshPending()"]');
    if (btn) {{ btn.disabled = true; btn.textContent = '🔄 刷新中…'; }}
    try {{
        const r = await fetch('/api/pending');
        const d = await r.json();
        const list = $('reqList');
        const reqs = d.requests || [];
        $('pendingCount').textContent = reqs.length ? `(共 ${{reqs.length}} 条等待)` : '';
        if (reqs.length === 0) {{
            list.innerHTML = '<div class="empty">暂无等待审批的请求</div>';
            return;
        }}
        list.innerHTML = reqs.map(req => renderReqCard(req)).join('');
    }} catch(e) {{
        $('reqList').innerHTML = '<div class="empty">刷新失败: ' + escapeHtml(e.message) + '</div>';
    }} finally {{
        _refreshing = false;
        if (btn) {{ btn.disabled = false; btn.textContent = '🔄 刷新列表'; }}
    }}
}}

function renderReqCard(req) {{
    const preview = req.latest_user || '';
    const sysLen = req.system_prompt_len || 0;
    const sysBadge = sysLen > 0
        ? `<span class="tag tag-warn" title="Claude Code 系统提示词将被过滤，不发给 DeepSeek">🛡️ 系统提示词 ${{sysLen}} 字符</span>`
        : '';
    const toolBadge = req.has_tool_results
        ? `<span class="tag tag-ok">🔧 工具结果</span>`
        : (req.has_tool_calls
            ? `<span class="tag tag-warn">🔧 含工具调用</span>`
            : '');
    return `
        <div class="req-card" id="card-${{req.id}}">
            <div class="req-head">
                <div class="req-info">
                    <div class="req-preview">${{escapeHtml(preview)}}</div>
                    <div class="req-meta">
                        <b>${{req.id}}</b>
                        <span>模型: ${{escapeHtml(req.model || '-')}}</span>
                        <span>用户: ${{req.user_count}} 条</span>
                        <span>助手: ${{req.assistant_count}} 条</span>
                        <span>等待: ${{req.waiting}}s</span>
                        ${{sysBadge}}
                        ${{toolBadge}}
                    </div>
                </div>
                <div class="req-actions">
                    <button class="btn-toggle" onclick="openModal('${{req.id}}')">查看详情</button>
                    <button class="btn-approve" onclick="doApprove('${{req.id}}')">放行</button>
                    <button class="btn-reject" onclick="doReject('${{req.id}}')">拒绝</button>
                </div>
            </div>
        </div>
    `;
}}

/* ── 模态弹窗 ─────────────────────────────────────── */

function openModal(reqId) {{
    $('modalTitle').textContent = '请求详情 · ' + reqId;
    $('modalMeta').textContent = '加载中…';
    $('modalBody').innerHTML = '<div style="text-align:center;color:#999;padding:30px;font-size:13px"><span class="spinner"></span>正在加载详情…</div>';
    $('modalFoot').innerHTML = '<button class="btn-ghost" onclick="closeModal()">关闭</button>';
    $('modal').classList.add('open');
    fetch('/api/request/' + reqId)
        .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
        .then(d => {{
            $('modalMeta').textContent =
                `模型: ${{d.model || '-'}} · 用户 ${{(d.user_messages||[]).length}} 条 · 助手 ${{(d.assistant_messages||[]).length}} 条 · 工具结果 ${{(d.tool_results||[]).length}} 条 · 等待 ${{d.waiting || 0}}s`;
            $('modalBody').innerHTML = renderDetail(d);
            $('modalFoot').innerHTML =
                `<button class="btn-ghost" onclick="closeModal()">关闭</button>
                 <button class="btn-approve" onclick="doApprove('${{reqId}}', true)">放行</button>
                 <button class="btn-reject" onclick="doReject('${{reqId}}', true)">拒绝</button>`;
        }})
        .catch(e => {{
            $('modalMeta').textContent = '加载失败';
            $('modalBody').innerHTML = '<div class="msg msg-err">加载失败: ' + escapeHtml(e.message) + '</div>';
        }});
}}

function closeModal() {{
    $('modal').classList.remove('open');
}}

/* ESC 关闭弹窗 */
document.addEventListener('keydown', e => {{
    if (e.key === 'Escape' && $('modal').classList.contains('open')) closeModal();
}});

function renderReqCard(req) {{
    const preview = req.latest_user || '';
    const sysLen = req.system_prompt_len || 0;
    const sysBadge = sysLen > 0
        ? `<span class="tag tag-warn" title="Claude Code 系统提示词将被过滤，不发给 DeepSeek">🛡️ 系统提示词 ${{sysLen}} 字符</span>`
        : '';
    const toolBadge = req.has_tool_results
        ? `<span class="tag tag-ok">🔧 工具结果</span>`
        : (req.has_tool_calls
            ? `<span class="tag tag-warn">🔧 含工具调用</span>`
            : '');
    return `
        <div class="req-card" id="card-${{req.id}}">
            <div class="req-head">
                <div class="req-info">
                    <div class="req-preview">${{escapeHtml(preview)}}</div>
                    <div class="req-meta">
                        <b>${{req.id}}</b>
                        <span>模型: ${{escapeHtml(req.model || '-')}}</span>
                        <span>用户: ${{req.user_count}} 条</span>
                        <span>助手: ${{req.assistant_count}} 条</span>
                        <span>等待: ${{req.waiting}}s</span>
                        ${{sysBadge}}
                        ${{toolBadge}}
                    </div>
                </div>
                <div class="req-actions">
                    <button class="btn-toggle" onclick="toggleDetail('${{req.id}}')">查看详情</button>
                    <button class="btn-approve" onclick="doApprove('${{req.id}}')">放行</button>
                    <button class="btn-reject" onclick="doReject('${{req.id}}')">拒绝</button>
                </div>
            </div>
            <div class="req-body" id="body-${{req.id}}">
                <div class="loading"><span class="spinner"></span>正在加载详情…</div>
            </div>
        </div>
    `;
}}

/* ── 详情展开 ─────────────────────────────────────── */

async function toggleDetail(reqId) {{
    const body = $('body-' + reqId);
    if (!body) return;
    if (body.classList.contains('open')) {{
        body.classList.remove('open');
        return;
    }}
    body.classList.add('open');
    body.innerHTML = '<div class="loading"><span class="spinner"></span>正在加载详情…</div>';
    try {{
        const r = await fetch('/api/request/' + reqId);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const d = await r.json();
        body.innerHTML = renderDetail(d);
    }} catch(e) {{
        body.innerHTML = '<div class="msg msg-err">加载失败: ' + escapeHtml(e.message) + '</div>';
    }}
}}

function renderDetail(d) {{
    const sysLen = d.system_prompt_len || 0;
    const sysPreview = d.system_prompt_preview || '';
    const sysFull = d.system_prompt_full || '';
    const userMsgs = d.user_messages || [];
    const asstMsgs = d.assistant_messages || [];
    const toolResults = d.tool_results || [];

    /* 系统提示词区 */
    let sysHtml = '';
    if (sysLen > 0) {{
        sysHtml = `
            <div class="sys-info">
                🛡️ 检测到 Claude Code 系统提示词，共 <b>${{sysLen}}</b> 字符 ·
                代理会丢弃它，<b>不会发给 DeepSeek</b>。
                （DeepSeek 不需要也不会读 system prompt）
            </div>
            <div class="code-box">${{escapeHtml(sysPreview || sysFull.slice(0, 500))}}${{sysFull.length > 500 ? '<span class="dim">\\n\\n…（已截断，共 '+sysFull.length+' 字符）</span>' : ''}}</div>
        `;
    }} else {{
        sysHtml = '<div class="sys-info">无 system prompt</div>';
    }}

    /* 用户消息 */
    let userHtml = '';
    if (userMsgs.length > 0) {{
        userHtml = userMsgs.map((parts, i) => {{
            const rendered = parts.map(p => renderPart(p)).join('');
            return `
                <div class="msg-block user">
                    <div class="msg-head"><span class="role">user</span><span class="idx">#${{i+1}}</span></div>
                    <div class="msg-text">${{rendered || '<span class=\\"empty\\">(空)</span>'}}</div>
                </div>
            `;
        }}).join('');
    }} else {{
        userHtml = '<div class="empty">无用户消息</div>';
    }}

    /* 助手消息 */
    let asstHtml = '';
    if (asstMsgs.length > 0) {{
        asstHtml = asstMsgs.map((parts, i) => {{
            const rendered = parts.map(p => renderPart(p)).join('');
            return `
                <div class="msg-block assistant">
                    <div class="msg-head"><span class="role">assistant</span><span class="idx">#${{i+1}}</span></div>
                    <div class="msg-text">${{rendered || '<span class=\\"empty\\">(空)</span>'}}</div>
                </div>
            `;
        }}).join('');
    }}

    /* 工具结果 */
    let toolHtml = '';
    if (toolResults.length > 0) {{
        toolHtml = toolResults.map((t, i) => `
            <div class="msg-block tool">
                <div class="msg-head">
                    <span class="role">tool_result</span>
                    <span class="idx">#${{i+1}}</span>
                    <span>id: ${{escapeHtml(t.tool_use_id)}}</span>
                    ${{t.is_error ? '<span class="tag tag-fail">is_error</span>' : ''}}
                </div>
                <div class="msg-text">${{escapeHtml(t.content)}}</div>
            </div>
        `).join('');
    }}

    /* 原始请求体 */
    const rawDisplay = d.request_data_display
        ? JSON.stringify(d.request_data_display, null, 2)
        : '';
    const origSize = d.request_data_size || 0;
    const sizeKB = origSize > 0 ? (origSize / 1024).toFixed(1) : '0';
    const sizeNote = origSize > 0
        ? `${{sizeKB}} KB · 已脱敏（老消息/系统提示词/tools 折叠成占位符，只保留最新 user 文本）`
        : '完整 JSON';

    return `
        <div class="section">
            <div class="section-title">🛡️ 系统提示词 <span class="badge">${{sysLen}} 字符 · 已过滤</span></div>
            ${{sysHtml}}
        </div>
        <div class="section">
            <div class="section-title">👤 用户消息 <span class="badge">${{userMsgs.length}} 条</span></div>
            ${{userHtml}}
        </div>
        ${{asstMsgs.length > 0 ? `
        <div class="section">
            <div class="section-title">🤖 助手消息 <span class="badge">${{asstMsgs.length}} 条</span></div>
            ${{asstHtml}}
        </div>
        ` : ''}}
        ${{toolResults.length > 0 ? `
        <div class="section">
            <div class="section-title">🔧 工具结果 <span class="badge">${{toolResults.length}} 条</span></div>
            ${{toolHtml}}
        </div>
        ` : ''}}
        <div class="section">
            <div class="section-title">📦 原始请求体（脱敏版） ${{sizeNote}}</div>
            <div class="code-box">${{escapeHtml(rawDisplay)}}</div>
        </div>
    `;
}}

function renderPart(p) {{
    /* p 是 [type, value] */
    const [type, val] = p;
    if (type === 'text') {{
        return `<span class="tool-tag text">text</span>${{escapeHtml(val)}}`;
    }} else if (type === 'tool_use') {{
        return `<span class="tool-tag use">tool_use</span>${{escapeHtml(val)}}`;
    }} else if (type === 'tool_result') {{
        return `<span class="tool-tag result">tool_result</span>${{escapeHtml(val)}}`;
    }} else if (type === 'thinking') {{
        return `<span class="tool-tag thinking">thinking</span><span style="color:#888">${{escapeHtml(val)}}</span>`;
    }}
    return `<span class="tool-tag">${{escapeHtml(type)}}</span>${{escapeHtml(val)}}`;
}}

/* ── 操作 ─────────────────────────────────────────── */

async function doApprove(id, fromModal) {{
    await fetch('/api/approve/' + id, {{method:'POST'}});
    if (fromModal) closeModal();
    refreshPending();
}}
async function doReject(id, fromModal) {{
    await fetch('/api/reject/' + id, {{method:'POST'}});
    if (fromModal) closeModal();
    refreshPending();
}}
async function doLogin() {{
    const btn = $('loginBtn');
    btn.disabled = true; btn.textContent = '登录中...';
    try {{
        const r = await fetch('/login', {{
            method:'POST',
            headers:{{'Content-Type':'application/json'}},
            body: JSON.stringify({{
                login_type: $('loginType').value,
                account: $('account').value,
                password: $('password').value
            }})
        }});
        const d = await r.json();
        showMsg('loginMsg', d.ok ? '✅ '+d.message : '❌ '+(d.error || '登录失败'), d.ok);
        if (d.ok) setTimeout(()=>location.reload(), 1000);
    }} catch(e) {{ showMsg('loginMsg', '❌ '+e.message, false); }}
    finally {{ btn.disabled = false; btn.textContent = '登录'; }}
}}
function showMsg(id, text, ok) {{
    const el = $(id);
    el.textContent = text;
    el.className = 'msg ' + (ok ? 'msg-ok' : 'msg-err');
}}

/* 启动时自动加载 session 列表 */
refreshSessions();

/* 不再自动刷新，需要手动点"刷新列表"按钮 */
</script>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin")


@app.post("/login")
async def login(request: Request):
    """登录 DeepSeek 并创建持久会话。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})

    login_type = body.get("login_type", "email")
    password = body.get("password", "")
    account = body.get("account", "") or body.get("email", "") or body.get("mobile", "")
    if not account or not password:
        return JSONResponse(status_code=400, content={"ok": False, "error": "account and password required"})

    result = ds_api.login(login_type, account, password)
    if result:
        return {"ok": True, "message": "Login successful, session created"}
    else:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Login failed. Check console for details."})


# ── 启动 ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    cfg = config.load_config()
    port = cfg.get("port", 8080)

    print(f"=== DeepSeek Web Agent Proxy ===")
    print(f"Listening on http://127.0.0.1:{port}")
    print(f"Authenticated: {bool(cfg.get('token'))}")
    print(f"Session: {cfg.get('session_id', 'N/A')[:16]}...")
    print()
    print("Endpoints:")
    print(f"  POST /v1/chat/completions  →  OpenAI Chat API (需要审批)")
    print(f"  POST /login                →  Login to DeepSeek")
    print(f"  GET  /health               →  Health check")
    print(f"  GET  /api/pending           →  待审批列表")
    print(f"  POST /api/approve/{'{id}'}    →  放行请求")
    print(f"  POST /api/reject/{'{id}'}    →  拒绝请求")
    print()

    uvicorn.run(app, host="0.0.0.0", port=port)
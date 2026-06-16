"""管理控制台页面模板

静态 HTML/CSS/JS，用 {STATUS_HTML} 等占位符接收动态数据。
使用 .format() 替换，避免 f-string 的 {{}} 冲突问题。
"""
import json


def escape_json_js(s):
    """JS 安全的字符串（嵌入 JSON.stringify 用）"""
    if s is None:
        return ""
    return json.dumps(s, ensure_ascii=False)[1:-1]


def render_admin_html(cfg, usage):
    """拼装管理控制台页面。"""
    status_tag_class = 'tag-ok' if cfg.get('token') else 'tag-fail'
    status_text = '✅ 已登录' if cfg.get('token') else '❌ 未登录'
    token_display = (cfg.get('token', '')[:24] + '…') if cfg.get('token') else '空'
    sid_display = (cfg.get('session_id', '')[:24] + '…') if cfg.get('session_id') else '空'
    ptokens = usage.get('prompt_tokens', 0)
    port = cfg.get('port', 8080)

    STATUS_HTML = f"""
<div class="card">
<h2>📊 状态</h2>
<div class="status-item"><span class="label">登录状态</span><span class="tag {status_tag_class}">{status_text}</span></div>
<div class="status-item"><span class="label">Token</span><span class="value">{token_display}</span></div>
<div class="status-item"><span class="label">会话 ID</span><span class="value">{sid_display}</span></div>
<div class="status-item"><span class="label">本 session 累计 token</span><span class="value">{ptokens}</span></div>
<div class="status-item"><span class="label">监听端口</span><span class="value">{port}</span></div>
</div>
"""

    # 核心：所有 HTML/CSS/JS 都在这里，用 {STATUS_HTML} 占位
    HTML = f"""<!DOCTYPE html>
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
.req-card {{ border:1px solid #e8e8e8; border-radius:10px; margin-bottom:10px; background:#fafafa; overflow:hidden; }}
.req-head {{ display:flex; align-items:center; gap:12px; padding:12px 14px; }}
.req-info {{ flex:1; min-width:0; }}
.req-preview {{ font-size:13px; color:#222; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-bottom:4px; }}
.req-preview:empty::before {{ content:'(空)'; color:#bbb; }}
.req-meta {{ font-size:11px; color:#999; display:flex; flex-wrap:wrap; gap:8px; }}
.req-meta b {{ color:#555; font-weight:600; }}
.req-actions {{ display:flex; gap:6px; flex-shrink:0; }}
.req-body {{ background:#fff; border-top:1px solid #e8e8e8; padding:14px; display:none; }}
.req-body.open {{ display:block; }}
.section {{ margin-bottom:14px; }}
.section:last-child {{ margin-bottom:0; }}
.section-title {{ font-size:12px; font-weight:600; color:#888; text-transform:uppercase; letter-spacing:.5px; margin-bottom:6px; display:flex; align-items:center; gap:8px; }}
.section-title .badge {{ background:#f0f0f0; color:#555; padding:1px 6px; border-radius:3px; font-size:11px; font-weight:500; text-transform:none; letter-spacing:0; }}
.sys-info {{ background:#fff7e6; border:1px solid #ffd591; border-radius:6px; padding:8px 10px; font-size:12px; color:#874d00; margin-bottom:8px; }}
.sys-info b {{ color:#d46b08; }}
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
.code-box {{ background:#1e1e1e; color:#d4d4d4; padding:10px 12px; border-radius:6px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; line-height:1.55; max-height:300px; overflow:auto; white-space:pre-wrap; word-break:break-word; }}
.code-box .dim {{ color:#888; }}
.empty {{ text-align:center; color:#ccc; padding:30px; font-size:14px; }}
.spinner {{ display:inline-block; width:12px; height:12px; border:2px solid #d9d9d9; border-top-color:#1677ff; border-radius:50%; animation:spin .8s linear infinite; margin-right:6px; vertical-align:middle; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
.modal-mask {{ position:fixed; inset:0; background:rgba(0,0,0,.45); display:none; align-items:center; justify-content:center; z-index:1000; padding:20px; }}
.modal-mask.open {{ display:flex; }}
.modal {{ background:#fff; border-radius:12px; width:100%; max-width:860px; max-height:90vh; display:flex; flex-direction:column; box-shadow:0 10px 40px rgba(0,0,0,.2); }}
.modal-head {{ padding:16px 20px; border-bottom:1px solid #eee; display:flex; justify-content:space-between; align-items:center; flex-shrink:0; }}
.modal-head h3 {{ font-size:16px; font-weight:600; color:#222; }}
.modal-head .meta {{ font-size:12px; color:#888; margin-top:2px; }}
.modal-close {{ background:transparent; color:#888; font-size:22px; line-height:1; padding:4px 10px; }}
.modal-body {{ padding:20px; overflow-y:auto; flex:1; }}
.modal-foot {{ padding:12px 20px; border-top:1px solid #eee; display:flex; justify-content:flex-end; gap:8px; flex-shrink:0; }}
.toolbar {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }}
.toolbar .left {{ font-size:13px; color:#666; }}
.toolbar .right {{ display:flex; gap:8px; }}
</style>
</head>
<body>
<div class="container">
<h1>🔌 DeepSeek Proxy</h1>
<div class="subtitle">DeepSeek 网页端 → OpenAI Chat Completions 反向代理 · 管理员审批控制台</div>

{STATUS_HTML}

<div class="card">
<div class="toolbar">
<h2 style="margin:0">💬 会话列表 <span id="sessionCount" style="font-size:12px;color:#999;font-weight:400"></span></h2>
<div class="right">
<button class="btn-ghost" onclick="refreshSessions()">🔃 刷新</button>
<button class="btn-primary" style="width:auto;padding:8px 14px;margin:0;font-size:13px" onclick="newSession()">➕ 新建会话</button>
</div>
</div>
<div id="sessionList"><div class="empty">点击右上"刷新"加载</div></div>
</div>

<div class="card">
<div class="toolbar">
<h2 style="margin:0">📥 待审批请求 <span id="pendingCount" style="font-size:12px;color:#999;font-weight:400"></span></h2>
<div class="right">
<button class="btn-ghost" onclick="refreshPending()">🔃 刷新列表</button>
</div>
</div>
<div id="reqList"><div class="empty">点击右上"刷新列表"加载</div></div>
</div>

<div class="modal-mask" id="modal" onclick="if(event.target===this) closeModal()">
  <div class="modal">
    <div class="modal-head">
      <div>
        <h3 id="modalTitle">请求详情</h3>
        <div class="meta" id="modalMeta"></div>
      </div>
      <button class="modal-close" onclick="closeModal()">&#x2715;</button>
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
<div class="toolbar">
<h2 style="margin:0">🛡️ 违规拦截规则 <span id="ruleCount" style="font-size:12px;color:#999;font-weight:400"></span></h2>
<div class="right">
<button class="btn-ghost" onclick="testRules()">🧪 测试</button>
<button class="btn-ghost" onclick="resetRules()">↺ 重置默认</button>
<button class="btn-ghost" onclick="refreshRules()">🔃 刷新</button>
<button class="btn-primary" style="width:auto;padding:8px 14px;margin:0;font-size:13px" onclick="openRuleForm()">➕ 新增规则</button>
</div>
</div>
<div id="ruleList"><div class="empty">点击右上"刷新"加载</div></div>
</div>

<div class="card">
<div class="toolbar">
<h2 style="margin:0">🎮 工具调用 <span id="toolConfigStatus" style="font-size:12px;color:#999;font-weight:400"></span></h2>
<div class="right">
<button class="btn-ghost" onclick="refreshToolConfig()">🔃 刷新</button>
<button class="btn-primary" style="width:auto;padding:8px 14px;margin:0;font-size:13px" onclick="initTools()">📤 发送初始化消息</button>
</div>
</div>
<div id="toolConfigCard">
<div class="empty">点击刷新加载</div>
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
    return String(s).replace(/[&<>"\\']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);
}}

/* ── Session 管理 ────────────────────────────────── */

async function refreshSessions() {{
    const btn = document.querySelector('button[onclick="refreshSessions()"]');
    if (btn) {{ btn.disabled = true; btn.textContent = '🔃 刷新中…'; }}
    try {{
        const r = await fetch('/api/sessions');
        const d = await r.json();
        const list = $('sessionList');
        const ss = d.sessions || [];
        $('sessionCount').textContent = ss.length ? ('(共 ' + escapeHtml(String(ss.length)) + ' 个)') : '';
        if (ss.length === 0) {{
            list.innerHTML = '<div class="empty">还没有 session，点右上"新建会话"创建</div>';
            return;
        }}
        list.innerHTML = ss.map(s => renderSessionCard(s)).join('');
    }} catch(e) {{
        $('sessionList').innerHTML = '<div class="empty">刷新失败: ' + escapeHtml(e.message) + '</div>';
    }} finally {{
        if (btn) {{ btn.disabled = false; btn.textContent = '🔃 刷新'; }}
    }}
}}

function renderSessionCard(s) {{
    const isActive = s.active;
    const activeBadge = isActive ? '<span class="tag tag-ok">🟢 当前活跃</span>' : '';
    const lastMid = s.last_message_id ? 'parent_message_id=' + escapeHtml(String(s.last_message_id)) : '无（根消息）';
    const lastUsed = s.last_used_at ? new Date(s.last_used_at * 1000).toLocaleString('zh-CN') : '-';
    const created = s.created_at ? new Date(s.created_at * 1000).toLocaleString('zh-CN') : '-';
    const label = s.label ? escapeHtml(s.label) + ' · ' : '';
    const sidShort = s.session_id ? escapeHtml(s.session_id.slice(0, 8)) + '…' + escapeHtml(s.session_id.slice(-4)) : '-';
    const switchBtn = isActive
        ? '<button class="btn-toggle" disabled>已激活</button>'
        : '<button class="btn-approve" onclick="activateSession(\\'' + escapeHtml(s.session_id) + '\\')">切换为此</button>';
    return '<div class="req-card" style="' + (isActive ? 'border-color:#52c41a;background:#f6ffed' : '') + '">'
        + '<div class="req-head">'
        + '<div class="req-info">'
        + '<div class="req-preview">' + label + escapeHtml(sidShort) + ' ' + activeBadge + '</div>'
        + '<div class="req-meta">'
        + '<b>消息数:</b> ' + (s.message_count || 0) + ' 条 <span>·</span> '
        + '<b>累计 token:</b> ' + (s.prompt_tokens || 0) + ' <span>·</span> '
        + '<b>续接:</b> ' + escapeHtml(lastMid) + ' <span>·</span> '
        + '<b>创建:</b> ' + escapeHtml(created) + ' <span>·</span> '
        + '<b>最后使用:</b> ' + escapeHtml(lastUsed)
        + '</div>'
        + '</div>'
        + '<div class="req-actions">' + switchBtn + '</div>'
        + '</div>'
        + '</div>';
}}

async function newSession() {{
    const label = prompt('给新会话起个名字（可选）', '');
    if (label === null) return;
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
            showMsg('loginMsg', '✅ 新会话已创建并激活：' + escapeHtml(d.session_id.slice(0, 8)) + '…', true);
            refreshSessions();
        }} else {{
            showMsg('loginMsg', '❌ ' + (d.error || '创建失败'), false);
        }}
    }} catch(e) {{
        showMsg('loginMsg', '❌ ' + escapeHtml(e.message), false);
    }} finally {{
        if (btn) {{ btn.disabled = false; btn.textContent = '➕ 新建会话'; }}
    }}
}}

async function activateSession(sid) {{
    if (!confirm('切换到 session ' + escapeHtml(sid.slice(0, 8)) + '…？\\n\\n下次 Claude Code 发消息会走这个 session。')) return;
    try {{
        const r = await fetch('/api/sessions/activate', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{session_id: sid}}),
        }});
        const d = await r.json();
        if (d.ok) {{
            showMsg('loginMsg', '✅ 已切换到 ' + escapeHtml(sid.slice(0, 8)) + '…', true);
            refreshSessions();
        }} else {{
            showMsg('loginMsg', '❌ ' + (d.error || '切换失败'), false);
        }}
    }} catch(e) {{
        showMsg('loginMsg', '❌ ' + escapeHtml(e.message), false);
    }}
}}

/* ── 列表刷新（手动） ─────────────────────────────── */

let _refreshing = false;

async function refreshPending() {{
    if (_refreshing) return;
    _refreshing = true;
    const btn = document.querySelector('button[onclick="refreshPending()"]');
    if (btn) {{ btn.disabled = true; btn.textContent = '🔃 刷新中…'; }}
    try {{
        const r = await fetch('/api/pending');
        const d = await r.json();
        const list = $('reqList');
        const reqs = d.requests || [];
        $('pendingCount').textContent = reqs.length ? '(共 ' + reqs.length + ' 条等待)' : '';
        if (reqs.length === 0) {{
            list.innerHTML = '<div class="empty">暂无等待审批的请求</div>';
            return;
        }}
        list.innerHTML = reqs.map(req => renderReqCard(req)).join('');
    }} catch(e) {{
        $('reqList').innerHTML = '<div class="empty">刷新失败: ' + escapeHtml(e.message) + '</div>';
    }} finally {{
        _refreshing = false;
        if (btn) {{ btn.disabled = false; btn.textContent = '🔃 刷新列表'; }}
    }}
}}

function renderReqCard(req) {{
    const preview = req.latest_user || '';
    const sysLen = req.system_prompt_len || 0;
    const sysBadge = sysLen > 0
        ? '<span class="tag tag-warn" title="Claude Code 系统提示词将被过滤，不发给 DeepSeek">🛡️ 系统提示词 ' + sysLen + ' 字符</span>'
        : '';
    const toolBadge = req.has_tool_results
        ? '<span class="tag tag-ok">🔧 工具结果</span>'
        : (req.has_tool_calls ? '<span class="tag tag-warn">🔧 含工具调用</span>' : '');
    return '<div class="req-card" id="card-' + escapeHtml(req.id) + '">'
        + '<div class="req-head">'
        + '<div class="req-info">'
        + '<div class="req-preview">' + escapeHtml(preview) + '</div>'
        + '<div class="req-meta">'
        + '<b>' + escapeHtml(req.id) + '</b> <span>模型: ' + escapeHtml(req.model || '-') + '</span> <span>用户: ' + req.user_count + ' 条</span> <span>助手: ' + req.assistant_count + ' 条</span> <span>等待: ' + (req.waiting || 0) + 's</span>'
        + sysBadge + toolBadge
        + '</div></div>'
        + '<div class="req-actions">'
        + '<button class="btn-toggle" onclick="openModal(\\'' + escapeHtml(req.id) + '\\')">查看详情</button>'
        + '<button class="btn-approve" onclick="doApprove(\\'' + escapeHtml(req.id) + '\\')">放行</button>'
        + '<button class="btn-reject" onclick="doReject(\\'' + escapeHtml(req.id) + '\\')">拒绝</button>'
        + '</div></div></div>';
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
            $('modalMeta').textContent = '模型: ' + (d.model || '-') + ' · 用户 ' + (d.user_messages||[]).length + ' 条 · 助手 ' + (d.assistant_messages||[]).length + ' 条 · 等待 ' + (d.waiting || 0) + 's';
            $('modalBody').innerHTML = renderDetail(d);
            $('modalFoot').innerHTML = '<button class="btn-ghost" onclick="closeModal()">关闭</button>'
                + '<button class="btn-approve" onclick="doApprove(\\'' + reqId + '\\', true)">放行</button>'
                + '<button class="btn-reject" onclick="doReject(\\'' + reqId + '\\', true)">拒绝</button>';
        }})
        .catch(e => {{
            $('modalMeta').textContent = '加载失败';
            $('modalBody').innerHTML = '<div class="msg msg-err">加载失败: ' + escapeHtml(e.message) + '</div>';
        }});
}}

function closeModal() {{
    $('modal').classList.remove('open');
}}

document.addEventListener('keydown', e => {{
    if (e.key === 'Escape' && $('modal').classList.contains('open')) closeModal();
}});

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
    const userMsgs = d.user_messages || [];
    const asstMsgs = d.assistant_messages || [];
    const toolResults = d.tool_results || [];
    const rawDisplay = d.request_data_display ? JSON.stringify(d.request_data_display, null, 2) : '';
    const origSize = d.request_data_size || 0;
    const sizeKB = origSize > 0 ? (origSize / 1024).toFixed(1) : '0';
    const sizeNote = origSize > 0 ? sizeKB + ' KB · 已脱敏' : '完整 JSON';

    let html = '<div class="section"><div class="section-title">🛡️ 系统提示词 <span class="badge">' + sysLen + ' 字符 · 已过滤</span></div>';
    if (sysLen > 0) {{
        html += '<div class="code-box">' + escapeHtml(d.system_prompt_preview || (d.system_prompt_full || '').slice(0, 500)) + '</div>';
    }} else {{
        html += '<div class="sys-info">无 system prompt</div>';
    }}
    html += '</div>';

    html += '<div class="section"><div class="section-title">👤 用户消息 <span class="badge">' + userMsgs.length + ' 条</span></div>';
    if (userMsgs.length === 0) {{
        html += '<div class="empty">无用户消息</div>';
    }} else {{
        userMsgs.forEach(function(parts, i) {{
            var text = parts.map(function(p) {{ return p[1] || ''; }}).join(' ');
            html += '<div class="msg-block user"><div class="msg-head"><span class="role">user</span><span class="idx">#' + (i+1) + '</span></div>'
                + '<div class="msg-text">' + escapeHtml(text || '(空)') + '</div></div>';
        }});
    }}
    html += '</div>';

    if (asstMsgs.length > 0) {{
        html += '<div class="section"><div class="section-title">🤖 助手消息 <span class="badge">' + asstMsgs.length + ' 条</span></div>';
        asstMsgs.forEach(function(parts, i) {{
            var text = parts.map(function(p) {{ return p[1] || ''; }}).join(' ');
            html += '<div class="msg-block assistant"><div class="msg-head"><span class="role">assistant</span><span class="idx">#' + (i+1) + '</span></div>'
                + '<div class="msg-text">' + escapeHtml(text || '(空)') + '</div></div>';
        }});
        html += '</div>';
    }}

    if (toolResults.length > 0) {{
        html += '<div class="section"><div class="section-title">🔧 工具结果 <span class="badge">' + toolResults.length + ' 条</span></div>';
        toolResults.forEach(function(t, i) {{
            html += '<div class="msg-block tool"><div class="msg-head"><span class="role">tool_result</span><span class="idx">#' + (i+1) + '</span></div>'
                + '<div class="msg-text">' + escapeHtml(t.content || '') + '</div></div>';
        }});
        html += '</div>';
    }}

    html += '<div class="section"><div class="section-title">📦 原始请求体（脱敏版） ' + sizeNote + '</div>';
    html += '<div class="code-box">' + escapeHtml(rawDisplay) + '</div></div>';

    return html;
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
    }} catch(e) {{ showMsg('loginMsg', '❌ '+escapeHtml(e.message), false); }}
    finally {{ btn.disabled = false; btn.textContent = '登录'; }}
}}
function showMsg(id, text, ok) {{
    const el = $(id);
    el.textContent = text;
    el.className = 'msg ' + (ok ? 'msg-ok' : 'msg-err');
}}

refreshSessions();

/* ── 违规拦截规则 ─────────────────────────────── */

async function refreshRules() {{
    const btn = document.querySelector('button[onclick="refreshRules()"]');
    if (btn) {{ btn.disabled = true; btn.textContent = '🔃 刷新中…'; }}
    try {{
        const r = await fetch('/api/rules');
        const d = await r.json();
        const list = $('ruleList');
        const rs = d.rules || [];
        $('ruleCount').textContent = rs.length ? '(共 ' + rs.length + ' 条 · ' + rs.filter(function(x){{return x.enabled;}}).length + ' 启用)' : '';
        if (rs.length === 0) {{
            list.innerHTML = '<div class="empty">还没有规则，点右上"新增规则"创建</div>';
            return;
        }}
        list.innerHTML = rs.map(function(r){{return renderRuleCard(r);}}).join('');
    }} catch(e) {{
        $('ruleList').innerHTML = '<div class="empty">刷新失败: ' + escapeHtml(e.message) + '</div>';
    }} finally {{
        if (btn) {{ btn.disabled = false; btn.textContent = '🔃 刷新'; }}
    }}
}}

function renderRuleCard(r) {{
    var onOff = r.enabled
        ? '<span class="tag tag-ok">✅ 启用</span>'
        : '<span class="tag" style="background:#f5f5f5;color:#999">⏸ 停用</span>';
    var typeLabel = r.type === 'keyword_substring' ? '关键词' : (r.type === 'regex' ? '正则' : (r.type === 'empty_clean_prompt' ? '空 prompt' : r.type));
    var scopeLabel = r.scope === 'body' ? '全文' : (r.scope === 'clean_prompt' ? '清洗后 prompt' : (r.scope === 'user_text_blocks' ? '用户 text 块' : r.scope));
    var patHtml = r.pattern ? '<code style="background:#f5f5f5;padding:1px 6px;border-radius:3px;font-size:12px">' + escapeHtml(r.pattern) + '</code>' : '<span style="color:#bbb">（无）</span>';
    var note = r.note ? '<div style="font-size:12px;color:#888;margin-top:4px">' + escapeHtml(r.note) + '</div>' : '';
    var toggleBtn = r.enabled
        ? '<button class="btn-toggle" onclick="toggleRule(\\'' + escapeHtml(r.id) + '\\', false)">停用</button>'
        : '<button class="btn-approve" onclick="toggleRule(\\'' + escapeHtml(r.id) + '\\", true)">启用</button>';
    return '<div class="req-card" style="' + (r.enabled ? '' : 'opacity:.55') + '">'
        + '<div class="req-head"><div class="req-info">'
        + '<div class="req-preview">' + onOff + ' <b>' + escapeHtml(r.name) + '</b> <span style="color:#999;font-size:12px">' + escapeHtml(r.id) + '</span></div>'
        + '<div class="req-meta"><b>类型:</b> ' + escapeHtml(typeLabel) + ' <span>·</span> <b>范围:</b> ' + escapeHtml(scopeLabel)
        + (r.case_sensitive ? ' <span>·</span><b>区分大小写</b>' : '')
        + ' <span>·</span> <b>pattern:</b> ' + patHtml + '</div>'
        + note + '</div><div class="req-actions">' + toggleBtn
        + '<button class="btn-toggle" onclick="openRuleForm(\\'' + escapeHtml(r.id) + '\\')">编辑</button>'
        + '<button class="btn-reject" onclick="deleteRule(\\'' + escapeHtml(r.id) + '\\')">删</button>'
        + '</div></div></div>';
}}

async function toggleRule(rid, enabled) {{
    try {{
        const r = await fetch('/api/rules/toggle/' + rid, {{
            method: 'POST',
            headers: {{'Content-Type':'application/json'}},
            body: JSON.stringify({{enabled: enabled}}),
        }});
        const d = await r.json();
        if (d.ok) refreshRules();
        else alert('切换失败：' + (d.error || ''));
    }} catch(e) {{ alert('切换失败：' + e.message); }}
}}

async function deleteRule(rid) {{
    if (!confirm('确定要删除规则 ' + rid + ' 吗？')) return;
    try {{
        const r = await fetch('/api/rules/delete/' + rid, {{method:'POST'}});
        const d = await r.json();
        if (d.ok) refreshRules();
        else alert('删除失败');
    }} catch(e) {{ alert('删除失败：' + e.message); }}
}}

async function resetRules() {{
    if (!confirm('确认重置为默认规则集？（已自定义的规则会丢失）')) return;
    try {{
        const r = await fetch('/api/rules/reset', {{method:'POST'}});
        const d = await r.json();
        if (d.ok) refreshRules();
        else alert('重置失败');
    }} catch(e) {{ alert('重置失败：' + e.message); }}
}}

function openRuleForm(rid) {{
    var isEdit = !!rid;
    var html = '<form id="ruleForm" onsubmit="return submitRuleForm(event,\\'' + (rid || '') + '\\')">'
        + '<label>规则名称 *</label><input name="name" required placeholder="比如：SUGGESTION MODE">'
        + '<label>类型 *</label><select name="type"><option value="keyword_substring">关键词子串（含则命中）</option><option value="regex">正则</option><option value="empty_clean_prompt">清洗后空 prompt（不需要 pattern）</option></select>'
        + '<label>范围</label><select name="scope"><option value="body">全文 body JSON</option><option value="clean_prompt">清洗后 prompt（剥过注入块）</option><option value="user_text_blocks">所有 user 消息的 text 块拼接</option></select>'
        + '<label>pattern（关键词或正则）</label><input name="pattern" placeholder="空 prompt 类型不用填">'
        + '<label style="display:flex;align-items:center;gap:6px"><input type="checkbox" name="case_sensitive" style="width:auto">区分大小写</label>'
        + '<label style="display:flex;align-items:center;gap:6px"><input type="checkbox" name="enabled" checked style="width:auto">启用</label>'
        + '<label>备注</label><input name="note" placeholder="说明这条规则挡什么">'
        + '<div style="display:flex;gap:8px;margin-top:14px;justify-content:flex-end">'
        + '<button type="button" class="btn-ghost" onclick="closeRuleForm()">取消</button>'
        + '<button type="submit" class="btn-primary" style="width:auto;margin:0;padding:10px 20px">' + (isEdit ? '保存' : '创建') + '</button></div></form>';
    openModalRaw(isEdit ? '编辑规则 · ' + rid : '新增规则', html, false);

    if (isEdit) {{
        fetch('/api/rules').then(function(r){{return r.json();}}).then(function(d){{
            var target = (d.rules || []).find(function(x){{return x.id === rid;}});
            if (!target) return;
            var f = document.getElementById('ruleForm');
            f.name.value = target.name || '';
            f.type.value = target.type || 'keyword_substring';
            f.scope.value = target.scope || 'body';
            f.pattern.value = target.pattern || '';
            f.case_sensitive.checked = !!target.case_sensitive;
            f.enabled.checked = target.enabled !== false;
            f.note.value = target.note || '';
        }});
    }}
}}

async function submitRuleForm(ev, rid) {{
    ev.preventDefault();
    var f = ev.target;
    var body = {{
        name: f.name.value.trim(),
        type: f.type.value,
        scope: f.scope.value,
        pattern: f.pattern.value,
        case_sensitive: f.case_sensitive.checked,
        enabled: f.enabled.checked,
        note: f.note.value.trim(),
    }};
    try {{
        var r;
        if (rid) {{
            r = await fetch('/api/rules/update/' + rid, {{
                method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body),
            }});
        }} else {{
            r = await fetch('/api/rules/add', {{
                method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body),
            }});
        }}
        var d = await r.json();
        if (d.ok) {{
            closeRuleForm();
            refreshRules();
        }} else {{
            alert('失败：' + (d.error || ''));
        }}
    }} catch(e) {{ alert('失败：' + escapeHtml(e.message)); }}
    return false;
}}

function openModalRaw(title, bodyHtml, withFoot) {{
    $('modalTitle').textContent = title;
    $('modalMeta').textContent = '';
    $('modalBody').innerHTML = bodyHtml;
    $('modalFoot').innerHTML = withFoot
        ? '<button class="btn-ghost" onclick="closeModal()">关闭</button>'
        : '<button class="btn-ghost" onclick="closeRuleForm()">关闭</button>';
    $('modal').classList.add('open');
}}

function closeRuleForm() {{ closeModal(); refreshRules(); }}

function testRules() {{
    var html = '<div><label>输入要测试的 prompt</label>'
        + '<textarea id="testPrompt" rows="6" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:6px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px" placeholder="比如：\\n[SUGGESTION MODE: Predict what the user might naturally type next]"></textarea>'
        + '<div style="display:flex;gap:8px;margin-top:10px;justify-content:flex-end">'
        + '<button class="btn-ghost" onclick="closeModal()">关闭</button>'
        + '<button class="btn-primary" style="width:auto;margin:0;padding:8px 16px" onclick="runRuleTest()">运行测试</button></div>'
        + '<div id="testResult" style="margin-top:14px"></div></div>';
    openModalRaw('🧪 规则命中测试', html, false);
}}

async function runRuleTest() {{
    var prompt = $('testPrompt').value;
    var r = await fetch('/api/rules/test', {{
        method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{prompt: prompt}}),
    }});
    var d = await r.json();
    var out = $('testResult');
    if (d.blocked) {{
        var f = d.first_hit || {{}};
        out.innerHTML = '<div class="msg msg-err" style="margin:0"><b>🚫 会被拦截</b>（命中规则 ' + escapeHtml(f.id || '?') + ' · ' + escapeHtml(f.name || '?') + '）</div>'
            + '<div style="font-size:12px;color:#888;margin-top:6px">清洗后 prompt 长度 = ' + d.clean_prompt_len + ' · 预览：' + escapeHtml(d.clean_prompt_preview || '(空)') + '</div>'
            + '<div style="margin-top:8px;font-size:12px;color:#666">共命中 ' + d.hits.length + ' 条规则：' + d.hits.map(function(h){{return h.id+'·'+h.name;}}).join('， ') + '</div>';
    }} else {{
        out.innerHTML = '<div class="msg msg-ok" style="margin:0"><b>✅ 不会被拦截</b></div>'
            + '<div style="font-size:12px;color:#888;margin-top:6px">清洗后 prompt 长度 = ' + d.clean_prompt_len + ' · 预览：' + escapeHtml(d.clean_prompt_preview || '(空)') + '</div>';
    }}
}}

/* ── 工具调用配置 ────────────────────────────────── */

async function refreshToolConfig() {{
    var btn = document.querySelector('button[onclick="refreshToolConfig()"]');
    if (btn) {{ btn.disabled = true; btn.textContent = '🔃 刷新中…'; }}
    try {{
        var r = await fetch('/api/tool-config');
        var d = await r.json();
        var tools = d.tools || {{}};
        var template = d.template || '';
        var names = Object.keys(tools);
        $('toolConfigStatus').textContent = '（' + names.length + ' 个工具）';

        var toolHtml = '';
        for (var idx = 0; idx < names.length; idx++) {{
            var name = names[idx];
            var spec = tools[name];
            var req = (spec.required || []).join(', ');
            var optEntries = Object.entries(spec.optional || {{}});
            var linesText = '';
            if (optEntries.length > 0) {{
                linesText = '<b>可选:</b><br>' + optEntries.map(function(kv){{return kv[0] + ': ' + kv[1];}}).join('<br>');
            }}
            toolHtml += '<div class="msg-block user" style="margin-top:8px">'
                + '<div class="msg-head"><span class="role">' + escapeHtml(name) + '</span><span class="idx">' + escapeHtml(spec.description || '') + '</span></div>'
                + '<div class="msg-text" style="font-size:12px"><b>必填:</b> ' + (escapeHtml(req) || '无') + '<br>' + linesText + '</div></div>';
        }}

        $('toolConfigCard').innerHTML = [
            '<div style="margin-bottom:10px;font-size:13px;display:flex;flex-wrap:wrap;gap:6px">',
            '  <span class="tag tag-ok">🎮 ' + names.length + ' 个工具</span>',
            '  <span class="tag">📝 模板 ' + template.length + ' 字符</span>',
            '</div>',
            '<div class="section">',
            '  <div class="section-title">📝 初始化模板</div>',
            '  <textarea id="tmplEditor" rows="6" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:6px;font-family:monospace;font-size:12px;line-height:1.5">' + escapeHtml(template) + '</textarea>',
            '  <div style="display:flex;gap:8px;margin-top:6px;justify-content:flex-end">',
            '    <button class="btn-ghost" onclick="saveToolConfig()">💾 保存模板</button>',
            '  </div>',
            '</div>',
            '<div class="section" style="margin-top:10px"><div class="section-title">🔧 工具定义</div>' + toolHtml + '</div>',
            '<div style="margin-top:10px;font-size:12px;color:#888">提示：点击"发送初始化消息"把模板 + 工具列表发给 DeepSeek 建立语境。</div>',
            '<div id="initMsg" style="margin-top:8px"></div>',
        ].join('\\n');
    }} catch(e) {{
        $('toolConfigCard').innerHTML = '<div class="empty">加载失败: ' + escapeHtml(e.message) + '</div>';
    }} finally {{
        if (btn) {{ btn.disabled = false; btn.textContent = '🔃 刷新'; }}
    }}
}}

async function saveToolConfig() {{
    var tmpl = $('tmplEditor').value;
    if (!tmpl.trim()) {{ alert('模板不能为空'); return; }}
    var btn = document.querySelector('#toolConfigCard .btn-ghost[onclick="saveToolConfig()"]');
    if (btn) {{ btn.textContent = '⏳ 保存中…'; btn.disabled = true; }}
    try {{
        var r = await fetch('/api/tool-config', {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{template: tmpl}}),
        }});
        var d = await r.json();
        if (d.ok) {{ showMsg('initMsg', '✅ 模板已保存', true); refreshToolConfig(); }}
        else {{ showMsg('initMsg', '❌ ' + (d.error || '保存失败'), false); }}
    }} catch(e) {{ showMsg('initMsg', '❌ ' + escapeHtml(e.message), false); }}
    finally {{ if (btn) {{ btn.textContent = '💾 保存模板'; btn.disabled = false; }} }}
}}

async function initTools() {{
    if (!confirm('确认发送初始化消息到 DeepSeek？\\n\\n这会把 \\"我们来玩一个游戏\\" + 工具列表 作为第一条消息发给当前 session。')) return;
    var btn = document.querySelector('button[onclick="initTools()"]');
    if (btn) {{ btn.textContent = '⏳ 发送中…'; btn.disabled = true; }}
    try {{
        var r = await fetch('/api/tool-config/init', {{method: 'POST'}});
        var d = await r.json();
        if (d.ok) {{ showMsg('initMsg', '✅ 已发送，DeepSeek 回复：' + escapeHtml(d.response_preview), true); refreshToolConfig(); }}
        else {{ showMsg('initMsg', '❌ ' + (d.error || '发送失败'), false); }}
    }} catch(e) {{ showMsg('initMsg', '❌ ' + escapeHtml(e.message), false); }}
    finally {{ if (btn) {{ btn.textContent = '📤 发送初始化消息'; btn.disabled = false; }} }}
}}

refreshToolConfig();
</script>
</body>
</html>"""

    # 用 STATUS_HTML 替换占位
    return HTML.replace('{STATUS_HTML}', STATUS_HTML)

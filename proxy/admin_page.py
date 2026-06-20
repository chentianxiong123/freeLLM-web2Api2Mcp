"""管理控制台页面模板

侧边栏导航布局，每个页面是一个独立的路由。
"""
import json


BASE_CSS = """\
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f0f2f5; color:#333; }

.sidebar { position:fixed; left:0; top:0; bottom:0; width:200px; background:#1a1a2e; color:#e0e0e0; display:flex; flex-direction:column; z-index:100; }
.sidebar-header { padding:16px; border-bottom:1px solid #2a2a3e; }
.sidebar-header h1 { font-size:14px; color:#fff; margin-bottom:2px; }
.sidebar-header .subtitle { font-size:10px; color:#888; }
.sidebar-nav { flex:1; padding:8px 0; overflow-y:auto; }
.nav-item { display:flex; align-items:center; gap:8px; padding:10px 16px; font-size:13px; color:#b0b0c0; text-decoration:none; transition:all .2s; cursor:pointer; border-left:3px solid transparent; }
.nav-item:hover { background:rgba(255,255,255,.05); color:#fff; }
.nav-item.active { background:rgba(255,255,255,.08); color:#1677ff; border-left-color:#1677ff; }
.nav-item .icon { font-size:14px; width:20px; text-align:center; }
.sidebar-footer { padding:12px 16px; border-top:1px solid #2a2a3e; font-size:10px; color:#666; }

.main { margin-left:200px; min-height:100vh; }
.main-header { background:#fff; padding:12px 20px; border-bottom:1px solid #e8e8e8; display:flex; align-items:center; gap:12px; }
.main-header h2 { font-size:15px; }
.main-header .right { margin-left:auto; font-size:11px; color:#999; }

.content { padding:16px 20px; max-width:960px; margin:0 auto; }

.card { background:#fff; border-radius:8px; padding:14px; margin-bottom:12px; box-shadow:0 1px 2px rgba(0,0,0,.05); }
h2 { font-size:13px; color:#333; margin-bottom:8px; font-weight:600; }
label { display:block; font-size:12px; font-weight:600; margin:8px 0 3px; }
input, select, textarea { width:100%; padding:8px 10px; border:1px solid #d9d9d9; border-radius:5px; font-size:12px; font-family:inherit; }
input:focus, select:focus, textarea:focus { outline:none; border-color:#1677ff; box-shadow:0 0 0 2px rgba(22,119,255,.1); }
button { padding:6px 12px; border:none; border-radius:5px; font-size:12px; cursor:pointer; font-family:inherit; transition:opacity .15s; }
button:hover { opacity:.8; }
button:disabled { opacity:.5; cursor:not-allowed; }

.btn-primary { background:#1677ff; color:#fff; }
.btn-ghost { background:#f5f5f5; color:#666; border:1px solid #d9d9d9; }
.btn-sm { padding:4px 8px; font-size:11px; }
.btn-danger { background:#ff4d4f; color:#fff; }
.btn-warn { background:#fa8c16; color:#fff; }

.status-row { display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid #f5f5f5; font-size:12px; }
.status-row:last-child { border:none; }
.status-row .lbl { color:#888; }
.status-row .val { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px; }
.tag { display:inline-block; padding:2px 6px; border-radius:3px; font-size:10px; font-weight:500; }
.tag-ok { background:#e6fffb; color:#006d75; }
.tag-fail { background:#fff2f0; color:#a8071a; }
.tag-warn { background:#fff7e6; color:#d46b08; }

.toolbar { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
.toolbar h2 { margin:0; }
.toolbar .actions { display:flex; gap:4px; }

.item-card { border:1px solid #e8e8e8; border-radius:6px; margin-bottom:6px; background:#fafafa; overflow:hidden; }
.item-head { display:flex; align-items:center; gap:8px; padding:8px 10px; }
.item-info { flex:1; min-width:0; }
.item-title { font-size:12px; color:#222; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-bottom:2px; }
.item-meta { font-size:10px; color:#999; display:flex; flex-wrap:wrap; gap:4px; }
.item-meta b { color:#666; font-weight:600; }
.item-actions { display:flex; gap:4px; flex-shrink:0; }

.empty { text-align:center; color:#ccc; padding:20px; font-size:12px; }

.intercept-row { border:1px solid #e8e8e8; border-radius:6px; margin-bottom:6px; cursor:pointer; transition:background .15s; }
.intercept-row:hover { background:#f5f5f5; }
.intercept-head { display:flex; align-items:center; gap:8px; padding:8px 10px; font-size:12px; }
.intercept-method { font-weight:600; color:#1677ff; min-width:40px; }
.intercept-path { flex:1; color:#333; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px; }
.intercept-status { min-width:30px; text-align:right; }
.intercept-status.ok { color:#389e0d; }
.intercept-status.err { color:#cf1322; }
.intercept-time { color:#999; font-size:10px; min-width:50px; text-align:right; }
.intercept-detail { display:none; padding:10px; background:#fff; border-top:1px solid #e8e8e8; font-size:11px; }
.intercept-detail.open { display:block; }
.intercept-detail pre { background:#f5f5f5; padding:8px; border-radius:4px; overflow:auto; max-height:200px; font-size:11px; white-space:pre-wrap; word-break:break-all; margin-top:4px; }
"""

SHARED_JS = """\
const $ = id => document.getElementById(id);

function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"\\']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}

function showToast(text, ok) {
    var t = $('toast');
    t.textContent = text;
    t.style.background = ok ? '#f6ffed' : '#fff2f0';
    t.style.color = ok ? '#389e0d' : '#cf1322';
    t.style.border = '1px solid ' + (ok ? '#b7eb8f' : '#ffa39e');
    t.style.display = 'block';
    t.style.opacity = '1';
    clearTimeout(t._timer);
    t._timer = setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.style.display = 'none', 300); }, 3000);
}

function closeModal() { $('modal').style.display = 'none'; }

function openModalRaw(title, bodyHtml) {
    $('modalTitle').textContent = title;
    $('modalMeta').textContent = '';
    $('modalBody').innerHTML = bodyHtml;
    $('modalFoot').innerHTML = '<button class="btn-ghost" onclick="closeModal()">关闭</button>';
    $('modal').style.display = 'flex';
}
"""


def escape_json_js(s):
    """JS 安全的字符串（嵌入 JSON.stringify 用）"""
    if s is None:
        return ""
    return json.dumps(s, ensure_ascii=False)[1:-1]


def _sidebar(active_page):
    """生成侧边栏 HTML"""
    nav_items = [
        ("/admin", "📊", "概览"),
        ("/admin/accounts", "👤", "账号"),
        ("/admin/sessions", "💬", "会话"),
        ("/admin/rules", "🛡️", "规则"),
        ("/admin/tools", "🎮", "工具"),
        ("/admin/parser-flow", "🔧", "解析器"),
        ("/admin/debug", "🔍", "调试"),
    ]
    links = ""
    for href, icon, label in nav_items:
        cls = " active" if href == active_page else ""
        links += f'  <a class="nav-item{cls}" href="{href}"><span class="icon">{icon}</span> {label}</a>\n'

    return f"""<div class="sidebar">
  <div class="sidebar-header">
    <h1>🔌 DeepSeek Proxy</h1>
    <span class="subtitle">v0.3.0</span>
  </div>
  <nav class="sidebar-nav">
{links}  </nav>
  <div class="sidebar-footer">DeepSeek Web Agent</div>
</div>"""


MODAL_HTML = """\
<div id="modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;justify-content:center;align-items:center" onclick="if(event.target===this)closeModal()">
<div style="background:#fff;border-radius:8px;width:90%;max-width:560px;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 8px 24px rgba(0,0,0,.2)">
  <div style="padding:12px 16px;border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between;align-items:center">
    <div><div id="modalTitle" style="font-size:14px;font-weight:600"></div><div id="modalMeta" style="font-size:10px;color:#999;margin-top:2px"></div></div>
    <button onclick="closeModal()" style="background:none;border:none;font-size:16px;cursor:pointer;color:#999">&times;</button>
  </div>
  <div id="modalBody" style="padding:16px;overflow-y:auto;flex:1"></div>
  <div id="modalFoot" style="padding:8px 16px;border-top:1px solid #f0f0f0;text-align:right"></div>
</div>
</div>"""

TOAST_HTML = """<div id="toast" style="position:fixed;top:16px;right:16px;z-index:2000;display:none;padding:8px 14px;border-radius:6px;font-size:12px;box-shadow:0 4px 12px rgba(0,0,0,.15);transition:opacity .3s"></div>"""


def _page_shell(title, sidebar_html, content_html, page_js=""):
    """生成完整页面外壳"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - DeepSeek Proxy 管理</title>
<style>
{BASE_CSS}</style>
</head>
<body>

{sidebar_html}

<div class="main">
  <div class="main-header">
    <h2>{title}</h2>
  </div>
  <div class="content">
{content_html}
  </div>
</div>

{MODAL_HTML}
{TOAST_HTML}

<script>
{SHARED_JS}
{page_js}
</script>
</body>
</html>"""


def render_overview(cfg, usage):
    """概览页"""
    status_tag_class = 'tag-ok' if cfg.get('token') else 'tag-fail'
    status_text = '✅ 已登录' if cfg.get('token') else '❌ 未登录'
    token_display = (cfg.get('token', '')[:24] + '…') if cfg.get('token') else '空'
    sid_display = (cfg.get('session_id', '')[:24] + '…') if cfg.get('session_id') else '空'
    inp_t = usage.get('input_tokens', 0)
    out_t = usage.get('output_tokens', 0)
    tot_t = usage.get('total_tokens', inp_t + out_t)
    msg_c = usage.get('message_count', 0)
    port = cfg.get('port', 48391)

    # 获取账号信息
    try:
        from accounts import list_accounts, get_active_account
        all_accs = list_accounts()
        active_acc = get_active_account()
        acc_count = len(all_accs)
        logged_in_count = sum(1 for a in all_accs if a.get('token'))
        active_label = active_acc.get('label', active_acc.get('id', '-')) if active_acc else '-'
    except Exception:
        acc_count = 0
        logged_in_count = 0
        active_label = '-'

    content = f"""<div class="card">
  <h2>📊 系统概览</h2>
  <div class="status-row"><span class="lbl">登录状态</span><span class="val"><span class="tag {status_tag_class}">{status_text}</span></span></div>
  <div class="status-row"><span class="lbl">Token</span><span class="val">{token_display}</span></div>
  <div class="status-row"><span class="lbl">Session ID</span><span class="val">{sid_display}</span></div>
  <div class="status-row"><span class="lbl">端口</span><span class="val">{port}</span></div>
  <div class="status-row"><span class="lbl">累计输入 Tokens</span><span class="val">{inp_t:,}</span></div>
  <div class="status-row"><span class="lbl">累计输出 Tokens</span><span class="val">{out_t:,}</span></div>
  <div class="status-row"><span class="lbl">累计总 Tokens</span><span class="val">{tot_t:,}</span></div>
  <div class="status-row"><span class="lbl">消息数</span><span class="val">{msg_c}</span></div>
</div>

<div class="card">
  <h2>👤 账号状态</h2>
  <div class="status-row"><span class="lbl">总账号数</span><span class="val">{acc_count}</span></div>
  <div class="status-row"><span class="lbl">已登录</span><span class="val"><span class="tag {'tag-ok' if logged_in_count > 0 else 'tag-fail'}">{logged_in_count} / {acc_count}</span></span></div>
  <div class="status-row"><span class="lbl">当前活跃</span><span class="val">{active_label}</span></div>
  <div style="margin-top:8px"><a class="btn-ghost btn-sm" href="/admin/accounts" style="text-decoration:none">管理账号 →</a></div>
</div>

<div class="card">
  <h2>🔗 快捷操作</h2>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px">
    <a class="btn-ghost btn-sm" href="/admin/accounts" style="text-decoration:none">👤 账号管理</a>
    <a class="btn-ghost btn-sm" href="/admin/sessions" style="text-decoration:none">💬 会话管理</a>
    <a class="btn-ghost btn-sm" href="/admin/rules" style="text-decoration:none">🛡️ 规则管理</a>
    <a class="btn-ghost btn-sm" href="/admin/tools" style="text-decoration:none">🎮 工具配置</a>
    <a class="btn-ghost btn-sm" href="/admin/debug" style="text-decoration:none">🔍 调试拦截</a>
  </div>
</div>"""

    sidebar = _sidebar("/admin")
    return _page_shell("概览", sidebar, content)


def render_accounts():
    """账号管理页"""
    content = """<div class="card">
  <div class="toolbar">
    <h2>👤 账号列表</h2>
    <div class="actions">
      <button class="btn-ghost btn-sm" onclick="refreshAccounts()">🔃 刷新</button>
      <button class="btn-ghost btn-sm" onclick="importOldAccount()">📥 导入旧配置</button>
      <button class="btn-primary btn-sm" onclick="openAddAccount()">➕ 添加并登录</button>
    </div>
  </div>
  <div id="accountList"><div class="empty">加载中...</div></div>
</div>"""

    js = """\
async function refreshAccounts() {
    try {
        var r = await fetch('/api/accounts');
        var d = await r.json();
        var accs = d.accounts || [];
        if (accs.length === 0) { $('accountList').innerHTML = '<div class="empty">暂无账号，点击"添加并登录"或"导入旧配置"</div>'; return; }
        $('accountList').innerHTML = accs.map(a => renderAccountCard(a)).join('');
    } catch(e) {
        $('accountList').innerHTML = '<div class="empty">加载失败: ' + escapeHtml(e.message) + '</div>';
    }
}

function renderAccountCard(a) {
    var active = a.active;
    var hasToken = !!a.token;
    var statusBadge = active
        ? (hasToken ? '<span class="tag tag-ok">● 当前</span>' : '<span class="tag tag-warn">● 当前(未登录)</span>')
        : (hasToken ? '<span class="tag tag-ok">● 已登录</span>' : '<span class="tag" style="background:#fff7e6;color:#fa8c16">● 未登录</span>');
    var accDisplay = escapeHtml((a.account || '').slice(0, 25));
    var lastUsed = a.last_used ? new Date(a.last_used * 1000).toLocaleString('zh-CN') : '-';
    var switchBtn = active
        ? ''
        : '<button class="btn-primary btn-sm" onclick="activateAccount(\\'' + a.id + '\\')">切换</button>';
    var loginBtn = hasToken
        ? '<button class="btn-ghost btn-sm" onclick="loginAccount(\\'' + a.id + '\\')">刷新登录</button>'
        : '<button class="btn-ghost btn-sm" style="color:#fa8c16;font-weight:600" onclick="loginAccount(\\'' + a.id + '\\')">⚠ 登录</button>';
    var delBtn = active
        ? ''
        : '<button class="btn-danger btn-sm" onclick="deleteAccount(\\'' + a.id + '\\')">删</button>';
    return '<div class="item-card" style="' + (active ? 'border-color:#52c41a;background:#f6ffed' : (hasToken ? '' : 'border-color:#fa8c16;background:#fffbe6')) + '">'
        + '<div class="item-head"><div class="item-info">'
        + '<div class="item-title">' + statusBadge + ' <b>' + escapeHtml(a.label || a.id) + '</b></div>'
        + '<div class="item-meta"><b>类型:</b> ' + a.login_type + ' <b>账号:</b> ' + accDisplay
        + (a.session_id ? ' <b>Session:</b> ' + escapeHtml(a.session_id.slice(0,8)) + '…' : '')
        + ' <b>最后使用:</b> ' + lastUsed
        + '</div></div><div class="item-actions">' + switchBtn + loginBtn + delBtn + '</div></div></div>';
}

function openAddAccount() {
    var html = '<form id="addAccForm" onsubmit="return submitAddAccount(event)">'
        + '<label>标签</label><input name="label" placeholder="主账号、测试号等" value="账号">'
        + '<label>登录方式</label><select name="login_type"><option value="email">邮箱</option><option value="phone">手机号</option></select>'
        + '<label>账号 *</label><input name="account" required placeholder="邮箱或手机号">'
        + '<label>密码 *</label><input name="password" type="password" required>'
        + '<div style="margin-top:8px;padding:8px;background:#f6ffed;border-radius:4px;font-size:12px;color:#52c41a">添加后会自动登录并保存 token</div>'
        + '<div style="display:flex;gap:6px;margin-top:10px;justify-content:flex-end">'
        + '<button type="button" class="btn-ghost" onclick="closeModal()">取消</button>'
        + '<button type="submit" class="btn-primary btn-sm">添加并登录</button></div></form>';
    openModalRaw('➕ 添加账号', html);
}

async function submitAddAccount(ev) {
    ev.preventDefault();
    var f = ev.target;
    var body = { label:f.label.value, login_type:f.login_type.value, account:f.account.value, password:f.password.value };
    try {
        var r = await fetch('/api/accounts/add', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
        var d = await r.json();
        if (d.ok) {
            closeModal();
            if (d.logged_in) { showToast('✅ 添加成功，已自动登录', true); }
            else { showToast('⚠ 已添加但登录失败: ' + (d.message||''), false); }
            refreshAccounts();
        } else { showToast('❌ ' + (d.error||'失败'), false); }
    } catch(e) { showToast('❌ ' + e.message, false); }
    return false;
}

async function activateAccount(id) {
    try {
        var r = await fetch('/api/accounts/activate/' + id, {method:'POST'});
        var d = await r.json();
        if (d.ok) { showToast('✅ 已切换', true); refreshAccounts(); }
    } catch(e) { showToast('❌ ' + e.message, false); }
}

async function loginAccount(id) {
    showToast('⏳ 登录中...', true);
    try {
        var r = await fetch('/api/accounts/login/' + id, {method:'POST'});
        var d = await r.json();
        if (d.ok) { showToast('✅ 登录成功', true); refreshAccounts(); }
        else { showToast('❌ ' + (d.error||'失败'), false); }
    } catch(e) { showToast('❌ ' + e.message, false); }
}

async function deleteAccount(id) {
    if (!confirm('确定删除此账号？')) return;
    try {
        var r = await fetch('/api/accounts/delete/' + id, {method:'POST'});
        var d = await r.json();
        if (d.ok) { showToast('✅ 已删除', true); refreshAccounts(); }
    } catch(e) { showToast('❌ ' + e.message, false); }
}

async function importOldAccount() {
    try {
        var r = await fetch('/api/accounts/import', {method:'POST'});
        var d = await r.json();
        showToast(d.ok ? '✅ 已导入' : 'ℹ️ ' + d.message, d.ok);
        refreshAccounts();
    } catch(e) { showToast('❌ ' + e.message, false); }
}

refreshAccounts();"""

    sidebar = _sidebar("/admin/accounts")
    return _page_shell("账号", sidebar, content, js)


def render_sessions():
    """会话管理页"""
    content = """<div class="card">
  <div class="toolbar">
    <h2>💬 会话列表 <span id="sessionCount" style="font-size:10px;color:#999;font-weight:400"></span></h2>
    <div class="actions">
      <button class="btn-ghost btn-sm" onclick="refreshSessions()">🔃 刷新</button>
      <button class="btn-ghost btn-sm" onclick="openImportSession()">📥 导入</button>
      <button class="btn-primary btn-sm" onclick="newSession()">➕ 新建</button>
    </div>
  </div>
  <div style="margin-bottom:8px;display:flex;align-items:center;gap:8px">
    <label style="font-size:11px;font-weight:600">新建模型：</label>
    <select id="newModelSelect" style="padding:4px 8px;border:1px solid #d9d9d9;border-radius:4px;font-size:11px">
      <option value="deepseek-v4-flash">🚀 Flash (快速)</option>
      <option value="deepseek-v4-pro">🧠 Pro (专家)</option>
    </select>
  </div>
  <div id="sessionList"><div class="empty">加载中...</div></div>
</div>"""

    js = """\
async function refreshSessions() {
    try {
        var r = await fetch('/api/sessions');
        var d = await r.json();
        var ss = d.sessions || [];
        $('sessionCount').textContent = ss.length ? '(' + ss.length + ')' : '';
        if (ss.length === 0) { $('sessionList').innerHTML = '<div class="empty">暂无会话</div>'; return; }
        $('sessionList').innerHTML = ss.map(s => renderSessionCard(s)).join('');
    } catch(e) { $('sessionList').innerHTML = '<div class="empty">加载失败</div>'; }
}

function renderSessionCard(s) {
    var active = s.active;
    var badge = active ? '<span class="tag tag-ok">当前</span>' : '';
    var mid = s.last_message_id ? 'mid=' + s.last_message_id : '根消息';
    var lastUsed = s.last_used_at ? new Date(s.last_used_at * 1000).toLocaleString('zh-CN') : '-';
    var label = s.label ? escapeHtml(s.label) + ' · ' : '';
    var sid = s.session_id || '';
    var sidShort = sid ? escapeHtml(sid.slice(0, 8)) + '…' : '-';
    var inp = s.input_tokens || 0;
    var out = s.output_tokens || 0;
    var total = s.total_tokens || (inp + out);
    var model = s.model || 'deepseek-v4-flash';
    var modelTag = model.includes('pro') ? '<span class="tag tag-warn">Pro</span>' : '<span class="tag tag-ok">Flash</span>';
    var switchBtn = active ? '' : '<button class="btn-primary btn-sm" onclick="activateSession(\\'' + escapeHtml(sid) + '\\')">切换</button>';
    var delBtn = active ? '' : '<button class="btn-danger btn-sm" onclick="deleteSession(\\'' + escapeHtml(sid) + '\\')">删</button>';
    return '<div class="item-card" style="' + (active ? 'border-color:#52c41a;background:#f6ffed' : '') + '">'
        + '<div class="item-head"><div class="item-info">'
        + '<div class="item-title">' + label + escapeHtml(sidShort) + ' ' + badge + ' ' + modelTag + '</div>'
        + '<div class="item-meta"><b>消息:</b> ' + (s.message_count || 0) + ' <b>↘输入:</b> ' + (inp).toLocaleString() + ' <b>↗输出:</b> ' + (out).toLocaleString() + ' <b>总计:</b> ' + (total).toLocaleString() + ' <b>续接:</b> ' + mid + ' <b>使用:</b> ' + lastUsed
        + '</div></div><div class="item-actions">' + switchBtn + delBtn + '</div></div></div>';
}

async function newSession() {
    var label = prompt('会话名称（可选）', '');
    if (label === null) return;
    var model = $('newModelSelect').value;
    try {
        var r = await fetch('/api/sessions/new', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({label:label, model:model}) });
        var d = await r.json();
        if (d.ok) { showToast('✅ 已创建 (' + model.replace('deepseek-v4-', '') + ')', true); refreshSessions(); }
        else { showToast('❌ ' + (d.error||'失败'), false); }
    } catch(e) { showToast('❌ ' + e.message, false); }
}

async function activateSession(sid) {
    try {
        var r = await fetch('/api/sessions/activate', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:sid}) });
        var d = await r.json();
        if (d.ok) { showToast('✅ 已切换', true); refreshSessions(); }
    } catch(e) { showToast('❌ ' + e.message, false); }
}

async function deleteSession(sid) {
    if (!confirm('确定删除？')) return;
    try {
        var r = await fetch('/api/sessions/delete', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:sid}) });
        var d = await r.json();
        if (d.ok) { showToast('✅ 已删除', true); refreshSessions(); }
    } catch(e) { showToast('❌ ' + e.message, false); }
}

function openImportSession() {
    var html = '<form id="importForm" onsubmit="return submitImportForm(event)">'
        + '<label>Session ID *</label><input name="session_id" required placeholder="UUID">'
        + '<label>续接 message_id</label><input name="last_message_id" type="number" placeholder="留空=新根消息">'
        + '<label>Label</label><input name="label" placeholder="可选">'
        + '<label style="display:flex;align-items:center;gap:6px;margin-top:8px"><input type="checkbox" name="activate" style="width:auto">导入后激活</label>'
        + '<div style="display:flex;gap:6px;margin-top:10px;justify-content:flex-end">'
        + '<button type="button" class="btn-ghost" onclick="closeModal()">取消</button>'
        + '<button type="submit" class="btn-primary btn-sm">导入</button></div></form>';
    openModalRaw('📥 导入 Session', html);
}

async function submitImportForm(ev) {
    ev.preventDefault();
    var f = ev.target;
    var raw = f.last_message_id.value.trim();
    var body = { session_id:f.session_id.value.trim(), label:f.label.value.trim(), activate:f.activate.checked, last_message_id:raw===''?null:parseInt(raw,10) };
    try {
        var r = await fetch('/api/sessions/import', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
        var d = await r.json();
        if (d.ok) { closeModal(); showToast('✅ 已导入', true); refreshSessions(); }
        else { alert('失败：' + (d.error || '')); }
    } catch(e) { alert('失败：' + e.message); }
    return false;
}

refreshSessions();"""

    sidebar = _sidebar("/admin/sessions")
    return _page_shell("会话", sidebar, content, js)


def render_rules():
    """规则管理页"""
    content = """<div class="card">
  <div class="toolbar">
    <h2>🛡️ 拦截规则 <span id="ruleCount" style="font-size:10px;color:#999;font-weight:400"></span></h2>
    <div class="actions">
      <button class="btn-ghost btn-sm" onclick="testRules()">🧪 测试</button>
      <button class="btn-ghost btn-sm" onclick="resetRules()">↺ 重置</button>
      <button class="btn-ghost btn-sm" onclick="refreshRules()">🔃 刷新</button>
      <button class="btn-primary btn-sm" onclick="openRuleForm()">➕ 新增</button>
    </div>
  </div>
  <div id="ruleList"><div class="empty">加载中...</div></div>
</div>"""

    js = """\
async function refreshRules() {
    try {
        var r = await fetch('/api/rules');
        var d = await r.json();
        var rs = d.rules || [];
        $('ruleCount').textContent = rs.length ? '(' + rs.length + ')' : '';
        if (rs.length === 0) { $('ruleList').innerHTML = '<div class="empty">暂无规则</div>'; return; }
        $('ruleList').innerHTML = rs.map(r => renderRuleCard(r)).join('');
    } catch(e) { $('ruleList').innerHTML = '<div class="empty">加载失败</div>'; }
}

function renderRuleCard(r) {
    var badge = r.enabled ? '<span class="tag tag-ok">启用</span>' : '<span class="tag" style="background:#f5f5f5;color:#999">停用</span>';
    var mt = r.match_type || 'substring';
    var scope = r.scope || 'request';
    var mtBadge = mt === 'regex'
        ? '<span class="tag" style="background:#fff7e6;color:#d46b08">regex</span>'
        : '<span class="tag" style="background:#e6f7ff;color:#096dd9">substring</span>';
    var scopeBadge = scope === 'response'
        ? '<span class="tag" style="background:#f6ffed;color:#389e0d">响应</span>'
        : '<span class="tag" style="background:#f0f5ff;color:#1d39c4">请求</span>';
    var pat = r.pattern ? '<code style="background:#f5f5f5;padding:1px 4px;border-radius:3px;font-size:10px">' + escapeHtml(r.pattern) + '</code>' : '';
    var toggleBtn = r.enabled
        ? '<button class="btn-ghost btn-sm" onclick="toggleRule(\\'' + r.id + '\\',false)">停用</button>'
        : '<button class="btn-primary btn-sm" onclick="toggleRule(\\'' + r.id + '\\',true)">启用</button>';
    return '<div class="item-card" style="' + (r.enabled ? '' : 'opacity:.6') + '">'
        + '<div class="item-head"><div class="item-info">'
        + '<div class="item-title">' + badge + ' ' + mtBadge + ' ' + scopeBadge + ' <b>' + escapeHtml(r.name) + '</b></div>'
        + '<div class="item-meta">' + pat + (r.note ? ' · ' + escapeHtml(r.note) : '') + '</div>'
        + '</div><div class="item-actions">' + toggleBtn
        + '<button class="btn-ghost btn-sm" onclick="openRuleForm(\\'' + r.id + '\\')">编辑</button>'
        + '<button class="btn-danger btn-sm" onclick="deleteRule(\\'' + r.id + '\\')">删</button>'
        + '</div></div></div>';
}

async function toggleRule(rid, enabled) {
    try { await fetch('/api/rules/toggle/' + rid, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({enabled:enabled}) }); refreshRules(); } catch(e) {}
}

async function deleteRule(rid) {
    if (!confirm('确定删除？')) return;
    try { await fetch('/api/rules/delete/' + rid, {method:'POST'}); refreshRules(); } catch(e) {}
}

async function resetRules() {
    if (!confirm('重置为默认规则？')) return;
    try { await fetch('/api/rules/reset', {method:'POST'}); showToast('✅ 已重置', true); refreshRules(); } catch(e) {}
}

function openRuleForm(rid) {
    var isEdit = !!rid;
    var html = '<form id="ruleForm" onsubmit="return submitRuleForm(event,\\'' + (rid||'') + '\\')">'
        + '<label>规则名称 *</label><input name="name" required placeholder="SYSTEM REMINDER">'
        + '<div style="display:flex;gap:8px">'
        + '<div style="flex:1"><label>匹配方式</label><select name="match_type"><option value="substring">substring</option><option value="regex">regex</option></select></div>'
        + '<div style="flex:1"><label>作用域</label><select name="scope"><option value="request">请求拦截</option><option value="response">响应过滤</option></select></div>'
        + '<div style="flex:1" id="actionField"><label>动作</label><select name="action"><option value="block">block 整个拦</option><option value="strip">strip 只删匹配</option></select></div>'
        + '</div>'
        + '<label>pattern</label><input name="pattern" required placeholder="&lt;system-reminder&gt;.*?&lt;/system-reminder&gt;">'
        + '<label style="display:flex;align-items:center;gap:6px"><input type="checkbox" name="enabled" checked style="width:auto">启用</label>'
        + '<label>备注</label><input name="note">'
        + '<div style="display:flex;gap:6px;margin-top:10px;justify-content:flex-end">'
        + '<button type="button" class="btn-ghost" onclick="closeModal()">取消</button>'
        + '<button type="submit" class="btn-primary btn-sm">' + (isEdit?'保存':'创建') + '</button></div></form>';
    openModalRaw(isEdit ? '编辑规则' : '新增规则', html);
    if (isEdit) {
        fetch('/api/rules').then(r=>r.json()).then(d => {
            var t = (d.rules||[]).find(x=>x.id===rid);
            if (!t) return;
            var f = $('ruleForm');
            f.name.value = t.name||'';
            f.pattern.value = t.pattern||'';
            f.match_type.value = t.match_type||'substring';
            f.scope.value = t.scope||'request';
            if (f.action) f.action.value = t.action||'block';
            f.enabled.checked = t.enabled!==false;
            f.note.value = t.note||'';
        });
    }
}

async function submitRuleForm(ev, rid) {
    ev.preventDefault();
    var f = ev.target;
    var body = {
        name: f.name.value.trim(),
        match_type: f.match_type.value,
        scope: f.scope.value,
        action: f.action ? f.action.value : 'block',
        pattern: f.pattern.value,
        enabled: f.enabled.checked,
        note: f.note.value.trim()
    };
    try {
        var url = rid ? '/api/rules/update/' + rid : '/api/rules/add';
        var r = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
        var d = await r.json();
        if (d.ok) { closeModal(); refreshRules(); }
    } catch(e) {}
    return false;
}

function testRules() {
    var html = '<div><label>输入测试内容</label>'
        + '<textarea id="testPrompt" rows="4" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;font-family:monospace;font-size:11px"></textarea>'
        + '<div style="display:flex;gap:6px;margin-top:8px;justify-content:flex-end">'
        + '<button class="btn-ghost" onclick="closeModal()">关闭</button>'
        + '<button class="btn-primary btn-sm" onclick="runRuleTest()">测试</button></div>'
        + '<div id="testResult" style="margin-top:8px"></div></div>';
    openModalRaw('🧪 规则测试', html);
}

async function runRuleTest() {
    var r = await fetch('/api/rules/test', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({prompt:$('testPrompt').value}) });
    var d = await r.json();
    var out = $('testResult');
    if (d.blocked) {
        out.innerHTML = '<div style="padding:6px;background:#fff2f0;border-radius:4px;font-size:11px;color:#cf1322"><b>🚫 拦截</b> — ' + escapeHtml((d.first_hit||{}).name||'?') + '</div>';
    } else {
        out.innerHTML = '<div style="padding:6px;background:#f6ffed;border-radius:4px;font-size:11px;color:#389e0d"><b>✅ 通过</b></div>';
    }
}

refreshRules();"""

    sidebar = _sidebar("/admin/rules")
    return _page_shell("规则", sidebar, content, js)


def render_tools():
    """工具配置页"""
    content = """<div class="card">
  <div class="toolbar">
    <h2>🎮 工具配置 <span id="toolConfigStatus" style="font-size:10px;color:#999;font-weight:400"></span></h2>
    <div class="actions">
      <button class="btn-ghost btn-sm" onclick="refreshToolConfig()">🔃 刷新</button>
      <button class="btn-primary btn-sm" onclick="initTools()">📤 发送初始化</button>
    </div>
  </div>
  <div style="margin-bottom:8px;display:flex;align-items:center;gap:8px">
    <label style="font-size:11px;font-weight:600">终端类型：</label>
    <select id="terminalSelect" onchange="changeTerminal()" style="padding:4px 8px;border:1px solid #d9d9d9;border-radius:4px;font-size:11px">
      <option value="powershell">PowerShell</option>
      <option value="cmd">CMD</option>
      <option value="bash">Bash (WSL/Linux)</option>
    </select>
    <span id="terminalHint" style="font-size:10px;color:#999"></span>
  </div>
  <div id="toolConfigCard"><div class="empty">加载中...</div></div>
</div>

"""

    js = """\
var currentTerminal = 'powershell';

async function refreshToolConfig() {
    try {
        // 获取终端类型
        var tr = await fetch('/api/config/terminal');
        var td = await tr.json();
        currentTerminal = td.terminal || 'powershell';
        $('terminalSelect').value = currentTerminal;
        $('terminalHint').textContent = getTerminalHint(currentTerminal);

        // 获取工具配置
        var r = await fetch('/api/tool-config');
        var d = await r.json();
        var tools = d.tools || {};
        var sections = d.sections || [];
        var names = Object.keys(tools);
        $('toolConfigStatus').textContent = '(' + names.length + ' 个工具, ' + sections.length + ' 个环节)';

        // sections UI
        var sectionsHtml = sections.map((sec, i) => {
            var isTools = sec.id === 'tools';
            var content = sec.content || '';
            return '<div style="padding:8px;background:#fafafa;border-radius:4px;margin-bottom:6px;border-left:2px solid ' + (sec.enabled ? '#1677ff' : '#d9d9d9') + '">'
                + '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">'
                + '<label style="display:flex;align-items:center;gap:4px;font-size:11px;cursor:pointer">'
                + '<input type="checkbox" id="sec_chk_' + i + '" ' + (sec.enabled ? 'checked' : '') + ' onchange="toggleSection(' + i + ')">'
                + '<span style="font-weight:600">' + escapeHtml(sec.title || sec.id) + '</span>'
                + '</label>'
                + '<span style="font-size:10px;color:#999">#' + sec.id + '</span>'
                + '<span style="font-size:10px;color:' + (sec.enabled ? '#52c41a' : '#999') + '">' + (sec.enabled ? '✅ 开启' : '⛔ 关闭') + '</span>'
                + '</div>'
                + (isTools
                    ? '<div style="font-size:10px;color:#888;padding:4px 6px;background:#f0f0f0;border-radius:3px">自动从工具定义生成</div>'
                    : '<textarea id="sec_txt_' + i + '" rows="2" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;font-family:monospace;font-size:11px">' + escapeHtml(content) + '</textarea>')
                + '</div>';
        }).join('');

        // 工具列表
        var toolHtml = names.map(name => {
            var spec = tools[name];
            var req = (spec.required||[]).join(', ') || '无';
            var opt = Object.keys(spec.optional||{}).join(', ') || '无';
            var example = getToolExample(name, currentTerminal);
            return '<div style="padding:8px;background:#fafafa;border-radius:4px;margin-bottom:6px;border-left:2px solid #1677ff">'
                + '<div style="font-size:12px;font-weight:600;color:#1677ff">' + escapeHtml(name) + '</div>'
                + '<div style="font-size:10px;color:#666;margin-top:4px">' + escapeHtml(spec.description||'') + '</div>'
                + '<div style="font-size:10px;color:#888;margin-top:4px"><b>必填:</b> ' + escapeHtml(req) + ' · <b>可选:</b> ' + escapeHtml(opt) + '</div>'
                + '<div style="margin-top:6px;padding:6px;background:#f5f5f5;border-radius:3px;font-family:monospace;font-size:10px;white-space:pre-wrap">' + escapeHtml(example) + '</div>'
                + '</div>';
        }).join('');

        $('toolConfigCard').innerHTML =
            '<div style="margin-bottom:6px;font-size:11px;color:#888">' + names.length + ' 个工具 · ' + sections.length + ' 个环节</div>'
            + '<div style="margin-bottom:8px"><b style="font-size:11px">📝 初始化消息环节（可开关/编辑，按顺序拼接）</b></div>'
            + sectionsHtml
            + '<div style="display:flex;gap:6px;margin-bottom:8px">'
            + '<button class="btn-ghost btn-sm" onclick="saveSections()">💾 保存环节</button>'
            + '<button class="btn-ghost btn-sm" onclick="previewInit()">👁 预览</button>'
            + '</div>'
            + '<div style="margin-bottom:8px;padding:8px;background:#fffbe6;border:1px solid #ffe58f;border-radius:4px;font-size:11px">'
            + '<b>📂 初始化参数（初始化时填入）</b>'
            + '<div style="display:flex;gap:8px;margin-top:4px">'
            + '<input id="initWorkDir" placeholder="工作目录（如 D:/my-project）" style="flex:1">'
            + '<input id="initProjectCtx" placeholder="项目背景（可选，如 Vue3 + TS）" style="flex:2">'
            + '</div>'
            + '</div>'
            + '<div><b style="font-size:11px">🔧 工具定义</b></div>' + toolHtml
            + '<div id="initPreview" style="margin-top:6px"></div>'
            + '<div id="initMsg" style="margin-top:6px"></div>';
    } catch(e) { $('toolConfigCard').innerHTML = '<div class="empty">加载失败</div>'; }
}

function getTerminalHint(t) {
    var hints = {
        'powershell': '使用 PowerShell 命令（Get-ChildItem 等）',
        'cmd': '使用 CMD 命令（dir 等）',
        'bash': '使用 Bash 命令（ls 等）'
    };
    return hints[t] || '';
}

function getToolExample(name, terminal) {
    var examples = {
        'Bash': {
            'powershell': '工具 Bash\\ncommand="Get-ChildItem C:\\\\Users | Select-Object -ExpandProperty Name"\\n工具结束',
            'cmd': '工具 Bash\\ncommand="dir C:\\\\Users /ad /b"\\n工具结束',
            'bash': '工具 Bash\\ncommand="ls -la /home"\\n工具结束'
        },
        'Read': {
            'powershell': '工具 Read\\nfile_path="config.json"\\n工具结束',
            'cmd': '工具 Read\\nfile_path="config.json"\\n工具结束',
            'bash': '工具 Read\\nfile_path="config.json"\\n工具结束'
        },
        'Write': {
            'powershell': '工具 Write\\nfile_path="hello.txt"\\ncontent="Hello World"\\n工具结束',
            'cmd': '工具 Write\\nfile_path="hello.txt"\\ncontent="Hello World"\\n工具结束',
            'bash': '工具 Write\\nfile_path="hello.txt"\\ncontent="Hello World"\\n工具结束'
        },
        'Edit': {
            'powershell': '工具 Edit\\nfile_path="config.txt"\\nold_string="old"\\nnew_string="new"\\n工具结束',
            'cmd': '工具 Edit\\nfile_path="config.txt"\\nold_string="old"\\nnew_string="new"\\n工具结束',
            'bash': '工具 Edit\\nfile_path="config.txt"\\nold_string="old"\\nnew_string="new"\\n工具结束'
        }
    };
    return (examples[name] && examples[name][terminal]) || '示例不可用';
}

async function changeTerminal() {
    var t = $('terminalSelect').value;
    try {
        await fetch('/api/config/terminal', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({terminal:t}) });
        currentTerminal = t;
        $('terminalHint').textContent = getTerminalHint(t);
        showToast('✅ 终端已切换为 ' + t, true);
        refreshToolConfig();
    } catch(e) { showToast('❌ 切换失败', false); }
}



function toggleSection(i) {
    var chk = $('sec_chk_' + i);
    var secs = getSectionsFromUI();
    if (secs[i]) secs[i].enabled = chk.checked;
    saveSectionsToServer(secs);
}

function getSectionsFromUI() {
    var secs = [];
    var i = 0;
    while ($('sec_chk_' + i)) {
        var sec = {
            id: '',
            enabled: $('sec_chk_' + i).checked,
            title: '',
        };
        var txt = $('sec_txt_' + i);
        sec.content = txt ? txt.value : '';
        i++;
        secs.push(sec);
    }
    return secs;
}

async function saveSectionsToServer(secs) {
    try {
        var r = await fetch('/api/tool-config', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({sections:secs}) });
        var d = await r.json();
        if (d.ok) { showToast('✅ 已保存', true); refreshToolConfig(); }
        else showToast('❌ 保存失败', false);
    } catch(e) { showToast('❌ ' + e.message, false); }
}

async function saveSections() {
    var secs = getSectionsFromUI();
    await saveSectionsToServer(secs);
}

async function previewInit() {
    var wd = $('initWorkDir').value || '.';
    var pc = $('initProjectCtx').value || '';
    try {
        var r = await fetch('/api/tool-config/init', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({working_directory: wd, project_context: pc, preview: true}) });
        var d = await r.json();
        if (d.prompt) {
            $('initPreview').innerHTML = '<div style="margin-top:8px;padding:8px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:4px">'
                + '<b style="font-size:11px;color:#389e0d">👁 预览（共 ' + d.prompt.length + ' 字符）</b>'
                + '<pre style="margin-top:4px;padding:8px;background:#fff;border:1px solid #e8e8e8;border-radius:4px;font-size:10px;white-space:pre-wrap;max-height:400px;overflow-y:auto">' + escapeHtml(d.prompt) + '</pre>'
                + '</div>';
        } else {
            $('initPreview').innerHTML = '<div class="empty">预览生成失败</div>';
        }
    } catch(e) { $('initPreview').innerHTML = '<div class="empty">' + escapeHtml(e.message) + '</div>'; }
}

async function initTools() {
    var wd = $('initWorkDir').value || '.';
    var pc = $('initProjectCtx').value || '';
    if (!confirm('发送初始化消息到 DeepSeek？\\n工作目录: ' + (wd || '.') + '\\n项目背景: ' + (pc || '(无)') + '\\n\\n先预览确认？')) return;
    try {
        var r = await fetch('/api/tool-config/init', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({working_directory: wd, project_context: pc}) });
        var d = await r.json();
        if (d.ok) showToast('✅ 已发送（' + (d.message_id ? 'mid='+d.message_id : '') + '）', true);
        else showToast('❌ ' + (d.error||'失败'), false);
    } catch(e) { showToast('❌ ' + e.message, false); }
}

refreshToolConfig();"""

    sidebar = _sidebar("/admin/tools")
    return _page_shell("工具", sidebar, content, js)


def render_parser_flow():
    """解析器流程说明页"""
    content = r"""<div class="card">
  <h2>🔍 解析器流程</h2>
  <div style="font-size:11px;color:#666;margin-bottom:8px">DeepSeek 返回自然语言格式，解析器用正则切出工具块，转成结构化 tool_calls</div>
  <div style="padding:10px;background:#f5f5f5;border-radius:6px;font-size:11px;line-height:1.8">
    <div><b>1. DeepSeek 原始回复</b>（自然语言暗语）</div>
    <pre style="margin:4px 0;padding:8px;background:#fff;border:1px solid #e8e8e8;border-radius:4px;font-size:11px;white-space:pre-wrap">好的，我先看看。

工具 Bash
command="Get-ChildItem C:/Users"
description="列出用户目录"
工具结束</pre>

    <div style="margin-top:8px"><b>2. 正则匹配</b>（tool_format.py）</div>
    <div style="padding:8px;background:#fff;border:1px solid #e8e8e8;border-radius:4px;margin:4px 0">
      <div style="font-family:monospace;font-size:10px;color:#666">TOOL_BLOCK_RE = 工具名行 + key=value行 + 工具结束</div>
      <div style="font-family:monospace;font-size:10px;color:#666;margin-top:4px">KEY_VALUE_RE = 匹配 key="value" 或 key=value</div>
    </div>

    <div style="margin-top:8px"><b>3. 解析结果</b>（结构化）</div>
    <pre style="margin:4px 0;padding:8px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:4px;font-size:11px">{
  "name": "Bash",
  "arguments": {
    "command": "Get-ChildItem C:/Users",
    "description": "列出用户目录"
  }
}</pre>

    <div style="margin-top:8px"><b>4. 类型推断</b></div>
    <div style="padding:8px;background:#fff;border:1px solid #e8e8e8;border-radius:4px;margin:4px 0;font-size:10px;color:#666">
      <div>- string → 保持字符串</div>
      <div>- integer → int(value)</div>
      <div>- number → float(value)</div>
      <div>- boolean → true/false → True/False</div>
      <div>- ~/路径 → 自动展开为绝对路径</div>
    </div>

    <div style="margin-top:8px"><b>5. 输出</b>（OpenAI tool_calls 格式）</div>
    <pre style="margin:4px 0;padding:8px;background:#e6f7ff;border:1px solid #91d5ff;border-radius:4px;font-size:11px">{
  "id": "call_xxx",
  "type": "function",
  "function": {
    "name": "Bash",
    "arguments": "{\"command\": \"Get-ChildItem C:/Users\"}"
  }
}</pre>

    <div style="margin-top:12px;padding:10px;background:#fffbe6;border:1px solid #ffe58f;border-radius:4px">
      <b style="font-size:11px">💡 实时解析测试</b>
      <div style="margin-top:6px">
        <textarea id="parseInput" rows="3" style="width:100%;padding:6px;border:1px solid #d9d9d9;border-radius:4px;font-family:monospace;font-size:11px" placeholder="粘贴一段 DeepSeek 回复，包含工具块...">工具 Bash
command="ls -la"
工具结束</textarea>
        <div style="text-align:right;margin-top:4px">
          <button class="btn-primary btn-sm" onclick="testParse()">▶ 解析</button>
        </div>
      </div>
      <pre id="parseOutput" style="margin-top:6px;padding:8px;background:#f5f5f5;border-radius:4px;font-size:11px;white-space:pre-wrap;min-height:40px;display:none"></pre>
    </div>
  </div>
</div>"""

    js = """\
async function testParse() {
    var input = $('parseInput').value;
    if (!input) return;
    try {
        var r = await fetch('/api/tool-config/parse', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text: input}) });
        var d = await r.json();
        var out = $('parseOutput');
        out.style.display = 'block';
        if (d.error) { out.innerHTML = '<span style=color:#cf1322>Error: ' + escapeHtml(d.error) + '</span>'; return; }
        out.innerHTML = '<b style=color:#389e0d>解析成功!</b>\\n' + escapeHtml(JSON.stringify(d.tool_calls, null, 2));
    } catch(e) { $('parseOutput').innerHTML = '<span style=color:#cf1322>' + escapeHtml(e.message) + '</span>'; }
}
testParse();"""

    sidebar = _sidebar("/admin/parser-flow")
    return _page_shell("解析器", sidebar, content, js)


def render_debug():
    """审批拦截页"""
    content = """<div class="card">
  <div class="toolbar">
    <h2>🔍 审批拦截 <span id="pendingCount" style="font-size:10px;color:#999;font-weight:400"></span></h2>
    <div class="actions">
      <button class="btn-ghost btn-sm" id="approvalToggle" onclick="toggleApproval()">▶️ 开启</button>
      <button class="btn-ghost btn-sm" id="transparentToggle" onclick="toggleTransparent()">👁 透明模式</button>
      <button class="btn-ghost btn-sm" onclick="approveAll()">✅ 全部放行</button>
      <button class="btn-ghost btn-sm" onclick="clearAll()">🗑 清空</button>
      <button class="btn-ghost btn-sm" onclick="refreshPending()">🔃 刷新</button>
    </div>
  </div>
  <div id="pendingList"><div class="empty">加载中...</div></div>
</div>

<div class="card" style="margin-top:12px">
  <div class="toolbar">
    <h2>📋 已审批历史</h2>
    <div class="actions">
      <button class="btn-ghost btn-sm" onclick="refreshHistory()">🔃 刷新</button>
    </div>
  </div>
  <div id="historyList"><div class="empty">加载中...</div></div>
</div>"""

    js = """\
async function refreshPending() {
    try {
        var r = await fetch('/api/approval/pending');
        var d = await r.json();
        var items = d.items || [];
        $('pendingCount').textContent = '(' + items.length + ')';
        $('approvalToggle').textContent = d.enabled ? '⏸ 关闭' : '▶️ 开启';
        $('approvalToggle').className = d.enabled ? 'btn-ghost btn-sm btn-warn' : 'btn-ghost btn-sm';
        $('transparentToggle').textContent = d.transparent ? '👁 透明模式(开)' : '👁 透明模式';
        $('transparentToggle').className = d.transparent ? 'btn-ghost btn-sm btn-warn' : 'btn-ghost btn-sm';
        if (items.length === 0) { $('pendingList').innerHTML = '<div class="empty">暂无待审批项</div>'; return; }
        $('pendingList').innerHTML = items.map(item => renderItem(item, true)).join('');
    } catch(e) { $('pendingList').innerHTML = '<div class="empty">加载失败</div>'; }
}

async function refreshHistory() {
    try {
        var r = await fetch('/api/approval/history?limit=30');
        var d = await r.json();
        var items = d.items || [];
        if (items.length === 0) { $('historyList').innerHTML = '<div class="empty">暂无历史</div>'; return; }
        $('historyList').innerHTML = items.map(item => renderItem(item, false)).join('');
    } catch(e) { $('historyList').innerHTML = '<div class="empty">加载失败</div>'; }
}

function renderItem(item, pending) {
    var time = item.timestamp ? new Date(item.timestamp * 1000).toLocaleTimeString('zh-CN') : '';
    var isReq = item.type === 'request';
    var badge = isReq
        ? '<span class="tag" style="background:#e6f7ff;color:#1890ff">请求</span>'
        : '<span class="tag" style="background:#f6ffed;color:#52c41a">响应</span>';
    var statusTag = '';
    if (!pending) {
        if (item.approved === true) statusTag = '<span class="tag tag-ok">已放行</span>';
        else if (item.approved === false) statusTag = '<span class="tag tag-fail">已拒绝</span>';
    }
    var header = item.method
        ? item.method + ' ' + item.path
        : (item.status ? item.status + ' OK' : item.path);
    var dur = item.duration_ms ? ' · ' + item.duration_ms.toFixed(0) + 'ms' : '';
    var editedBadge = item.edited_body ? ' <span class="tag" style="background:#fff7e6;color:#d46b08">已编辑</span>' : '';

    // 预览：前 200 字符
    var preview = '';
    if (item.body) {
        try { preview = JSON.stringify(item.body, null, 2); } catch(e) { preview = String(item.body); }
        preview = preview.slice(0, 200) + (preview.length > 200 ? '...' : '');
    }
    // 转换预览
    var convPreview = '';
    if (item.conversion && item.conversion.user_content) {
        convPreview = item.conversion.user_content.slice(0, 100) + (item.conversion.user_content.length > 100 ? '...' : '');
    }

    var actions = '';
    if (pending) {
        var editLabel = isReq ? '✏️ 编辑内容' : '✏️ 编辑响应';
        actions = '<div class="item-actions">'
            + '<button class="btn-ghost btn-sm" onclick="openEditModal(' + item.id + ', \\'' + escapeHtml(isReq ? '请求' : '响应') + '\\')">' + editLabel + '</button>'
            + '<button class="btn-primary btn-sm" onclick="doApprove(' + item.id + ')">✅ 放行</button>'
            + '<button class="btn-danger btn-sm" onclick="doReject(' + item.id + ')">❌ 拒绝</button>'
            + '</div>';
    }

    return '<div class="item-card" style="margin-bottom:8px">'
        + '<div class="item-head" style="cursor:pointer">'
        + '<div class="item-info">'
        + '<div class="item-title">' + badge + ' <span style="font-family:monospace;font-size:12px">' + escapeHtml(header) + '</span> ' + statusTag + editedBadge + '</div>'
        + '<div class="item-meta">' + time + dur + '</div>'
        + (convPreview ? '<div class="item-meta" style="color:#52c41a">用户消息: ' + escapeHtml(convPreview) + '</div>' : '')
        + '</div>' + actions
        + '</div>'
        + '<div class="item-detail" style="display:flex;gap:6px;flex-wrap:wrap;padding:8px">'
        + '<button class="btn-ghost btn-sm" onclick="showFullJson(' + item.id + ', \\'' + escapeHtml(isReq ? '请求 Body' : '响应 Body') + '\\')">📋 查看完整 JSON</button>'
        + (convPreview ? '<button class="btn-ghost btn-sm" onclick="showFullConv(' + item.id + ')">🔄 查看转换结果</button>' : '')
        + '</div>'
        + '</div>';
}

async function showFullJson(id, title) {
    // 从 pending 或 history 获取完整数据
    try {
        var r = await fetch('/api/approval/history?limit=100');
        var d = await r.json();
        var item = (d.items || []).find(i => i.id === id);
        if (!item) { r = await fetch('/api/approval/pending'); d = await r.json(); item = (d.items || []).find(i => i.id === id); }
        if (!item) { showToast('未找到', false); return; }
        var json = JSON.stringify(item.body, null, 2);
        openModalRaw(title, '<pre id="fullJsonPre" style="margin:0;white-space:pre-wrap;word-break:break-all;font-size:12px;line-height:1.5;max-height:70vh;overflow:auto;background:#f5f5f5;padding:12px;border-radius:4px">' + escapeHtml(json) + '</pre>'
            + '<div style="margin-top:8px;text-align:right"><button class="btn-ghost btn-sm" onclick="copyJson()">📋 复制</button></div>');
    } catch(e) { showToast('加载失败', false); }
}

async function showFullConv(id) {
    try {
        var r = await fetch('/api/approval/history?limit=100');
        var d = await r.json();
        var item = (d.items || []).find(i => i.id === id);
        if (!item) { r = await fetch('/api/approval/pending'); d = await r.json(); item = (d.items || []).find(i => i.id === id); }
        if (!item || !item.conversion) { showToast('未找到', false); return; }
        var conv = item.conversion;
        var html = '<div style="font-size:12px;line-height:1.8">'
            + '<div><b>类型:</b> ' + (conv.is_react_continuation ? 'React 续接' : '新对话') + '</div>'
            + '<div><b>消息数:</b> ' + (conv.messages_count || 0) + '</div>'
            + '<div style="margin-top:8px"><b>用户消息:</b></div>'
            + '<pre style="margin:0;white-space:pre-wrap;word-break:break-all;font-size:12px;line-height:1.5;max-height:60vh;overflow:auto;background:#f6ffed;padding:12px;border-radius:4px;border:1px solid #b7eb8f">' + escapeHtml(conv.user_content || '(空)') + '</pre>'
            + '</div>';
        openModalRaw('🔄 转换结果 (build_ds_input)', html);
    } catch(e) { showToast('加载失败', false); }
}

function copyJson() {
    var el = document.getElementById('fullJsonPre');
    if (el) { navigator.clipboard.writeText(el.textContent).then(() => showToast('已复制', true)); }
}

async function toggleApproval() {
    try { await fetch('/api/approval/toggle', {method:'POST'}); refreshPending(); } catch(e) {}
}

async function toggleTransparent() {
    try {
        var r = await fetch('/api/approval/transparent', {method:'POST'});
        var d = await r.json();
        $('transparentToggle').textContent = d.transparent ? '👁 透明模式(开)' : '👁 透明模式';
        $('transparentToggle').className = d.transparent ? 'btn-ghost btn-sm btn-warn' : 'btn-ghost btn-sm';
        showToast(d.transparent ? '✅ 透明模式开启：直接放行但留痕' : '✅ 透明模式关闭', true);
    } catch(e) {}
}

async function doApprove(id) {
    try { await fetch('/api/approval/approve/' + id, {method:'POST'}); refreshPending(); refreshHistory(); } catch(e) {}
}

async function doReject(id) {
    try { await fetch('/api/approval/reject/' + id, {method:'POST'}); refreshPending(); refreshHistory(); } catch(e) {}
}

async function approveAll() {
    try { await fetch('/api/approval/approve-all', {method:'POST'}); refreshPending(); refreshHistory(); } catch(e) {}
}

async function clearAll() {
    try { await fetch('/api/approval/clear', {method:'POST'}); refreshPending(); refreshHistory(); } catch(e) {}
}

var currentEditId = null;
var currentEditType = null;

async function openEditModal(id, type) {
    currentEditId = id;
    currentEditType = type;
    try {
        var r = await fetch('/api/approval/pending');
        var d = await r.json();
        var item = (d.items || []).find(i => i.id === id);
        if (!item) { showToast('未找到', false); return; }

        var editContent = '';
        var title = '';
        if (type === '请求') {
            // 请求：编辑 conversion.user_content（发给 DeepSeek 的最终消息）
            var conv = item.conversion || {};
            editContent = (item.edited_body && item.edited_body.user_content) ? item.edited_body.user_content : (conv.user_content || '');
            title = '✏️ 编辑发送内容（user_content）';
        } else {
            // 响应：编辑最终 OpenAI response
            var body = item.body;
            if (item.edited_body) body = item.edited_body;
            editContent = JSON.stringify(body, null, 2);
            title = '✏️ 编辑响应（OpenAI Response）';
        }

        var html = '<div style="font-size:12px;margin-bottom:8px;color:#666">' + (type === '请求' ? '修改发给 DeepSeek 的消息' : '修改返回给客户端的响应') + '</div>'
            + '<textarea id="editBodyArea" style="width:100%;height:400px;padding:8px;border:1px solid #d9d9d9;border-radius:4px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;white-space:pre-wrap;word-break:break-all;resize:vertical">' + escapeHtml(editContent) + '</textarea>'
            + '<div style="display:flex;gap:6px;margin-top:8px;justify-content:flex-end">'
            + '<button class="btn-ghost" onclick="closeModal()">取消</button>'
            + '<button class="btn-primary btn-sm" onclick="saveEditBody()">💾 保存</button></div>';
        openModalRaw(title, html);
    } catch(e) { showToast('加载失败', false); }
}

async function saveEditBody() {
    if (!currentEditId) return;
    var text = $('editBodyArea').value;

    var edited;
    if (currentEditType === '请求') {
        // 请求：保存为 {user_content: "..."}
        edited = {user_content: text};
    } else {
        // 响应：解析 JSON
        try { edited = JSON.parse(text); } catch(e) { showToast('JSON 格式错误', false); return; }
    }

    try {
        var r = await fetch('/api/approval/edit/' + currentEditId, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({body:edited}) });
        var d = await r.json();
        if (d.ok) { closeModal(); showToast('✅ 已保存，点放行生效', true); refreshPending(); }
        else { showToast('❌ ' + (d.error||'失败'), false); }
    } catch(e) { showToast('❌ ' + e.message, false); }
}

refreshPending();
refreshHistory();
setInterval(refreshPending, 2000);  // 自动刷新待审批列表"""

    sidebar = _sidebar("/admin/debug")
    return _page_shell("审批拦截", sidebar, content, js)

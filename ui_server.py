"""自建 Web 后台 —— 控制网页版 LLM 核心层（外援老师 MCP 底座）。

基于 WebLLMRelay 核心层（webllmrelay 包）重建的简洁 UI，自己控制：

- 查看平台（列表 / 登录态 / 已验证 / 可用浏览器）
- 登录平台（起 login_worker 弹「系统 Chrome」登录窗口，人工登录）
- 检测登录态 / 测试调用（复用核心层 providers）
- 切换浏览器（chrome / msedge，均复用本机不下载）

用法：
    python ui_server.py                 # 默认 0.0.0.0:8787
    python ui_server.py --port 8787
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from tutor import ask
from tutor import cookies
from tutor import login as tutor_login
from tutor.config import (
    get_browser,
    get_cdp_url,
    get_interval,
    get_mode,
    set_browser,
    set_cdp_url,
    set_interval,
    set_mode,
)

app = FastAPI(title="网页LLM 外援老师后台")

# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------


class AskReq(BaseModel):
    platform: str
    prompt: str
    conversation_id: str = ""


class BrowserReq(BaseModel):
    value: str


class SettingsReq(BaseModel):
    mode: str = ""
    cdp: str = ""
    min_interval: float | None = None
    max_interval: float | None = None


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------

HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>网页LLM 外援老师后台</title>
<style>
  :root { --bg:#0f1115; --card:#171a21; --line:#2a2f3a; --tx:#e6e8ee; --mut:#8b93a3;
          --ok:#2fbf71; --warn:#e6a23c; --err:#e35d5d; --acc:#4a8cff; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:ui-sans-serif,system-ui,"Segoe UI",sans-serif; background:var(--bg); color:var(--tx); }
  header { padding:20px 28px; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:16px; }
  header h1 { font-size:18px; margin:0; }
  header .sub { color:var(--mut); font-size:13px; }
  main { max-width:1100px; margin:24px auto; padding:0 20px; }
  .bar { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:18px; }
  .bar select, .bar button { background:var(--card); color:var(--tx); border:1px solid var(--line);
          border-radius:8px; padding:8px 14px; font-size:14px; cursor:pointer; }
  .bar button:hover { border-color:var(--acc); }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:16px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; }
  .card h3 { margin:0 0 4px; font-size:16px; }
  .card .url { color:var(--mut); font-size:12px; word-break:break-all; margin-bottom:10px; }
  .badges { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
  .badge { font-size:12px; padding:3px 10px; border-radius:99px; }
  .badge.ok { background:rgba(47,191,113,.15); color:var(--ok); }
  .badge.no { background:rgba(139,147,163,.15); color:var(--mut); }
  .badge.warn { background:rgba(230,162,60,.15); color:var(--warn); }
  .ops { display:flex; gap:8px; flex-wrap:wrap; }
  .ops button { background:var(--card); color:var(--tx); border:1px solid var(--line);
          border-radius:8px; padding:7px 12px; font-size:13px; cursor:pointer; }
  .ops button:hover { border-color:var(--acc); }
  .ask { margin-top:14px; border-top:1px solid var(--line); padding-top:12px; }
  .ask textarea { width:100%; min-height:56px; background:var(--bg); color:var(--tx);
          border:1px solid var(--line); border-radius:8px; padding:8px; font-size:13px; resize:vertical; }
  .ask .row { display:flex; gap:8px; margin-top:8px; align-items:center; }
  .ask .row input { flex:1; background:var(--bg); color:var(--tx); border:1px solid var(--line);
          border-radius:8px; padding:7px 10px; font-size:13px; }
  .ask .ans { margin-top:8px; background:var(--bg); border:1px solid var(--line); border-radius:8px;
          padding:10px; font-size:13px; white-space:pre-wrap; max-height:180px; overflow:auto; color:var(--mut); }
  .ask .ans.show { color:var(--tx); }
  .log { margin-top:10px; font-size:12px; color:var(--mut); }
  footer { text-align:center; color:var(--mut); font-size:12px; padding:24px; }
</style>
</head>
<body>
<header>
  <h1>🧑‍🏫 网页LLM 外援老师后台</h1>
  <span class="sub">核心层 = WebLLMRelay（AGPL-3.0）· 浏览器复用本机不下载</span>
</header>
<main>
  <div class="bar">
    <label style="font-size:14px;color:var(--mut)">浏览器</label>
    <select id="browser"></select>
    <button onclick="setBrowser()">切换</button>
    <span id="browserInfo" style="font-size:13px;color:var(--mut)"></span>
  </div>
  <div class="card" style="margin-bottom:18px">
    <h3 style="font-size:14px;margin:0 0 10px">⚙️ 运行模式（风控）</h3>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <select id="mode">
        <option value="persistent">persistent（自带profile，登录一次复用）</option>
        <option value="cdp">cdp（连真浏览器，风控最小）</option>
      </select>
      <input id="cdp" placeholder="CDP地址 http://127.0.0.1:9222" style="width:230px;background:var(--bg);color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font-size:13px">
      <input id="minInt" type="number" step="0.5" style="width:68px;background:var(--bg);color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:7px;font-size:13px" title="最小间隔秒">
      <span style="color:var(--mut);font-size:12px">~</span>
      <input id="maxInt" type="number" step="0.5" style="width:68px;background:var(--bg);color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:7px;font-size:13px" title="最大间隔秒">
      <span style="color:var(--mut);font-size:12px">秒(提问间隔)</span>
      <button onclick="saveSettings()">保存</button>
      <button onclick="exportState()">导出登录态</button>
      <button onclick="importState()">导入登录态</button>
      <button onclick="runHealthCheck()">🔎 一键健康检查</button>
    </div>
  </div>
  <div class="grid" id="grid"><div class="card">加载中…</div></div>
</main>
<footer>外援老师 MCP 底座 · 自建 UI · 登录后用「检测」确认 · 测试提问验证可用</footer>

<script>
let PLATS = [];
async function j(url, opt) {
  const r = await fetch(url, opt);
  if (!r.ok) throw new Error((await r.text()).slice(0,200) || r.status);
  return r.json();
}
async function refresh() {
  const d = await j('/api/platforms');
  PLATS = d;
  const grid = document.getElementById('grid');
  grid.innerHTML = d.map(p => `
    <div class="card">
      <h3>${p.name} <span style="color:var(--mut);font-size:12px">${p.key}</span></h3>
      <div class="url">${p.url}</div>
      <div class="badges">
        <span class="badge ${p.logged_in ? 'ok' : 'no'}">${p.logged_in ? '✅ 已登录' : '⬜ 未登录'}</span>
        <span class="badge ${p.verified ? 'ok' : 'warn'}">${p.verified ? '🔧 已验证' : '⚠️ 未验证'}</span>
      </div>
      <div class="ops">
        <button onclick="login('${p.key}')">🔑 登录</button>
        <button onclick="check('${p.key}',this)">🔍 检测</button>
      </div>
      <div class="ask">
        <textarea placeholder="测试提示词，如：帮我搜一下最近的大模型新闻"></textarea>
        <div class="row">
          <input placeholder="conversation_id（续聊，可空）">
          <button onclick="ask('${p.key}',this)">▶ 提问</button>
        </div>
        <div class="ans"></div>
      </div>
      <div class="log"></div>
    </div>`).join('');
  await loadBrowser();
  await loadSettings();
}
async function loadBrowser() {
  const b = await j('/api/browser');
  const sel = document.getElementById('browser');
  sel.innerHTML = b.available.map(v => `<option value="${v}" ${v===b.current?'selected':''}>${v}</option>`).join('');
  document.getElementById('browserInfo').textContent = '当前: ' + b.current;
}
async function setBrowser() {
  const v = document.getElementById('browser').value;
  await j('/api/browser', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({value:v})});
  await loadBrowser();
  alert('已切换浏览器为 ' + v + '（复用本机，不下载）');
}
async function loadSettings() {
  const s = await j('/api/settings');
  document.getElementById('mode').value = s.mode;
  document.getElementById('cdp').value = s.cdp || '';
  document.getElementById('minInt').value = s.min_interval;
  document.getElementById('maxInt').value = s.max_interval;
}
async function saveSettings() {
  const body = {
    mode: document.getElementById('mode').value,
    cdp: document.getElementById('cdp').value.trim(),
    min_interval: parseFloat(document.getElementById('minInt').value),
    max_interval: parseFloat(document.getElementById('maxInt').value)
  };
  const s = await j('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  alert('已保存：模式=' + s.mode + ' 间隔=' + s.min_interval + '~' + s.max_interval + 's');
}
async function exportState() {
  try {
    const r = await j('/api/state/export', {method:'POST'});
    alert('登录态已导出: ' + r.path);
  } catch(e) { alert('导出失败: ' + e.message); }
}
async function importState() {
  try {
    const r = await j('/api/state/import', {method:'POST'});
    alert('已注入 ' + r.count + ' 个 cookie');
  } catch(e) { alert('导入失败: ' + e.message); }
}
async function runHealthCheck() {
  if (!confirm('全自动健康检查：连浏览器检测所有平台登录态（约30-60s）？')) return;
  try {
    const r = await j('/api/check_all', {method:'POST'});
    const ok = r.ok.map(x => x.name).join('、') || '无';
    const need = r.need.map(x => x.name).join('、') || '无';
    alert('✅ 已登录: ' + ok + '\n⬜ 需登录: ' + need);
  } catch(e) { alert('检查失败: ' + e.message); }
  refresh();
}
async function login(key) {
  await j('/api/login/start?key=' + key, {method:'POST'});
  alert('已打开 ' + key + ' 登录窗口（系统 Chrome）。登录完关闭窗口，再点「检测」。');
}
async function check(key, btn) {
  btn.disabled = true; btn.textContent = '检测中…';
  try {
    const r = await j('/api/login/check?key=' + key, {method:'POST'});
    alert(r.logged_in ? key + ' 已登录 ✅' : key + ' 未登录 ⬜');
  } catch(e) { alert('检测失败: ' + e.message); }
  btn.disabled = false; btn.textContent = '🔍 检测';
  refresh();
}
async function ask(key, btn) {
  const card = btn.closest('.card');
  const prompt = card.querySelector('textarea').value.trim();
  const cid = card.querySelector('input').value.trim();
  const ans = card.querySelector('.ans');
  const log = card.querySelector('.log');
  if (!prompt) { alert('先填测试提示词'); return; }
  btn.disabled = true; btn.textContent = '提问中…'; ans.textContent = '请求中…'; ans.classList.remove('show');
  try {
    const r = await j('/api/ask', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({platform:key, prompt, conversation_id:cid})});
    ans.textContent = r.answer || '(空)'; ans.classList.add('show');
    log.textContent = '平台: ' + r.platform + ' · cid: ' + (r.conversation_id||'-');
  } catch(e) {
    ans.textContent = '❌ ' + e.message; ans.classList.add('show');
  }
  btn.disabled = false; btn.textContent = '▶ 提问';
}
refresh();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@app.get("/api/platforms")
def api_platforms() -> list[dict]:
    return ask.list_llms()


AVAILABLE_BROWSERS = ["chrome", "msedge"]  # 系统浏览器（复用本机，不下载）


@app.get("/api/browser")
def api_browser() -> dict:
    return {"current": get_browser(), "available": AVAILABLE_BROWSERS}


@app.post("/api/browser")
def api_set_browser(req: BrowserReq) -> dict:
    set_browser(req.value)
    return {"current": get_browser(), "available": AVAILABLE_BROWSERS}


@app.get("/api/settings")
def api_settings() -> dict:
    lo, hi = get_interval()
    return {
        "mode": get_mode(),
        "browser": get_browser(),
        "cdp": get_cdp_url(),
        "min_interval": lo,
        "max_interval": hi,
    }


@app.post("/api/settings")
def api_set_settings(req: SettingsReq) -> dict:
    if req.mode:
        set_mode(req.mode)
    if req.cdp != "":
        set_cdp_url(req.cdp)
    if req.min_interval is not None and req.max_interval is not None:
        set_interval(req.min_interval, req.max_interval)
    return api_settings()


@app.post("/api/state/export")
def api_export_state() -> dict:
    p = cookies.export_state()
    return {"ok": True, "path": p}


@app.post("/api/state/import")
def api_import_state() -> dict:
    n = cookies.import_state(str(cookies.DEFAULT_EXPORT))
    return {"ok": True, "count": n}


@app.post("/api/login/start")
def api_login_start(key: str, mode: str = "login") -> dict:
    """起 login_worker 子进程，弹「系统 Chrome」登录窗口。"""
    return tutor_login.start_login(key, mode)


@app.post("/api/login/check")
def api_login_check(key: str) -> dict:
    return ask.check_login(key)


@app.post("/api/ask")
def api_ask(req: AskReq) -> dict:
    return ask.ask_llm(req.platform, req.prompt, req.conversation_id)


@app.post("/api/check_all")
def api_check_all() -> dict:
    """全自动健康检查：遍历所有平台检测登录态。"""
    results = ask.check_all()
    return {
        "results": results,
        "ok": [r for r in results if r.get("logged_in")],
        "need": [r for r in results if not r.get("logged_in")],
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="网页LLM 外援老师后台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

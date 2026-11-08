"""登录态（cookie/localStorage）导出与导入。

用途：
- export_state：把当前会话登录态导出为 JSON（storage_state 格式）。
  在 CDP 模式下 = 导出「真浏览器」的真 cookie（Playwright 通过 CDP 自动解密，明文）；
  在 persistent 模式 = 导出自己 profile 的登录态。可跨机/备份。
- import_state：把导出的登录态注入到会话（add_cookies），换机恢复登录。
- get_cookies：读取当前会话明文 cookie（含登录态）。
"""

from __future__ import annotations

import json

from tutor.browser import BrowserSession
from tutor.config import DATA_DIR

DEFAULT_EXPORT = DATA_DIR / "login_state_export.json"


def export_state(path: str = "") -> str:
    """导出当前会话登录态为 JSON（storage_state 格式），返回路径。"""
    path = path or str(DEFAULT_EXPORT)
    bs = BrowserSession()
    with bs.session() as ctx:
        ctx.storage_state(path=path)
    return path


def import_state(path: str) -> int:
    """从导出的 JSON 注入登录态（add_cookies），返回注入 cookie 数。"""
    data = json.loads(open(path, encoding="utf-8").read())
    cookies = data.get("cookies", [])
    bs = BrowserSession()
    with bs.session() as ctx:
        if cookies:
            ctx.add_cookies(cookies)
    return len(cookies)


def get_cookies(domain: str = "") -> list[dict]:
    """读取当前会话明文 cookie（可按域名过滤）。"""
    bs = BrowserSession()
    with bs.session() as ctx:
        cookies = ctx.cookies()
    if domain:
        cookies = [c for c in cookies if domain in c.get("domain", "")]
    return cookies

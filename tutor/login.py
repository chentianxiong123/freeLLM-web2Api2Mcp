"""登录：起独立进程弹「系统 Chrome」到平台页，人工登录后关窗。"""

from __future__ import annotations

import subprocess
import sys

from tutor.config import ROOT, get_provider


def start_login(key: str, mode: str = "login") -> dict:
    """校验平台并启动登录窗口子进程（独立进程，复用本机浏览器）。"""
    spec = get_provider(key)
    log_f = open(ROOT / "data" / "logs" / "login.log", "a", encoding="utf-8")
    subprocess.Popen(
        [sys.executable, "-m", "tutor.login_worker", key, "--mode", mode],
        cwd=str(ROOT),
        stdout=log_f,
        stderr=log_f,
        start_new_session=True,
    )
    return {"ok": True, "key": key, "name": spec.name, "mode": mode}

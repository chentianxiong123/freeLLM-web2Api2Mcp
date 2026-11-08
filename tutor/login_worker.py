"""登录工作进程（独立）：弹系统 Chrome 到平台页，人工登录后关窗。

由 login.start_login 通过 subprocess 启动，持有 profile 锁与 MCP 调用互斥。
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from playwright.sync_api import sync_playwright

from tutor.browser import BROWSER_ARGS, STEALTH, channel, profile_dir
from tutor.config import get_provider
from tutor.lock import ProfileLock

MAX_SECONDS = 30 * 60  # 窗口最长保留 30 分钟


def main() -> int:
    parser = argparse.ArgumentParser(description="打开平台登录窗口")
    parser.add_argument("provider")
    parser.add_argument("--mode", choices=["login", "open"], default="login")
    args = parser.parse_args()

    spec = get_provider(args.provider)
    ud = profile_dir()
    lock = ProfileLock(ud + ".lock", timeout=0)
    lock.acquire()

    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=ud,
                channel=channel(),
                headless=False,  # 登录必须可见
                handle_sigint=False,
                handle_sigterm=False,
                args=BROWSER_ARGS,
            )
            ctx.add_init_script(STEALTH)
            closed = threading.Event()
            ctx.on("close", lambda: closed.set())
            browser = getattr(ctx, "browser", None)
            if browser is not None:
                try:
                    browser.on("disconnected", lambda: closed.set())
                except Exception:  # noqa: BLE001
                    pass

            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(spec.url, wait_until="domcontentloaded", timeout=45000)
            except Exception as exc:  # noqa: BLE001 - 加载失败仍允许人工操作
                print(f"跳转 {spec.url} 失败: {exc}", file=sys.stderr)

            print(
                f"已打开 {spec.name} 窗口: {spec.url}\n"
                f"请在窗口中完成登录，完成后关闭浏览器窗口即可。",
                file=sys.stderr,
            )

            deadline = time.monotonic() + MAX_SECONDS
            while not closed.is_set() and time.monotonic() < deadline:
                try:
                    if not ctx.pages:
                        time.sleep(0.5)
                        if not ctx.pages:
                            break
                        continue
                    ctx.pages[0].evaluate("1")
                except Exception:  # noqa: BLE001 - 断开=窗口被关
                    break
                time.sleep(1.0)

            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
    finally:
        lock.release()

    print("登录窗口已关闭，登录态已保存在持久化 profile。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

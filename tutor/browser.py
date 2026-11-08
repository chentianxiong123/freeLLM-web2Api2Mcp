"""浏览器会话管理：复用本机浏览器（不下载）+ 反指纹 + profile 会话锁。

- channel 按设置选：chrome / msedge 都复用系统浏览器（零下载）；chromium = 内置（需另行安装）。
- 持久化 profile：登录态跨进程/跨重启保留。
- session() 上下文管理器：进入拿锁+确保启动，退出关闭+释放锁。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import BrowserContext, sync_playwright

from tutor.config import get_browser, get_cdp_url, get_headless, get_mode, profile_dir
from tutor.lock import ProfileLock

# 反自动化指纹（通用技巧）：掩盖 webdriver / 伪装 chrome / plugins / languages
STEALTH = """() => {
  Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
  const _chrome = { runtime:{},
    loadTimes: () => ({startE:0,startL:0,endE:0,onloadT:0,pageT:0,firstPaint:0,firstContentfulPaint:0,firstMeaningfulPaint:0}),
    csi: () => ({}) };
  Object.defineProperty(window, 'chrome', {get: () => _chrome});
  const _names = ['PDF Viewer','Chrome PDF Viewer','Chromium PDF Viewer','Microsoft Edge PDF Viewer','WebKit built-in PDF'];
  const _arr = _names.map(n => ({name:n, filename:n, description:n, length:1, item:()=>null, namedItem:()=>null}));
  _arr.item = (i) => _arr[i] || null;
  _arr.namedItem = (n) => _arr.find(p => p.name === n) || null;
  Object.defineProperty(navigator, 'plugins', {get: () => _arr});
  Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh']});
}"""

# 额外启动参数（降低自动化特征）
BROWSER_ARGS = ["--disable-blink-features=AutomationControlled"]


def channel() -> str:
    """当前浏览器设置对应的 Playwright channel。"""
    b = get_browser()
    if b == "chrome":
        return "chrome"
    if b == "msedge":
        return "msedge"
    return "chromium"


class BrowserSession:
    """单例浏览器会话（复用系统浏览器 + 持久化 profile + 锁）。"""

    def __init__(self) -> None:
        self._pw = None
        self._context: BrowserContext | None = None
        self._browser = None
        self._cdp = False
        self._lock: ProfileLock | None = None

    # -- 内部 --------------------------------------------------------

    def _launch(self, headless: bool) -> None:
        self._pw = sync_playwright().start()
        if get_mode() == "cdp" and get_cdp_url():
            # CDP 模式：连接已打开的真浏览器，复用其登录态（指纹/账号真实，风控最小）
            self._cdp = True
            self._browser = self._pw.chromium.connect_over_cdp(get_cdp_url())
            # 复用用户默认 context（含登录态）；无则新建
            self._context = (
                self._browser.contexts[0]
                if self._browser.contexts
                else self._browser.new_context()
            )
            self._context.add_init_script(STEALTH)
        else:
            # persistent 模式：自带持久化 profile（登录一次，之后复用）
            self._cdp = False
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=profile_dir(),
                channel=channel(),
                headless=headless,
                handle_sigint=False,
                handle_sigterm=False,
                args=BROWSER_ARGS,
            )
            self._context.add_init_script(STEALTH)

    def _alive(self) -> bool:
        try:
            return self._context is not None and self._context.is_connected()
        except Exception:  # noqa: BLE001 - 断开一律视为不可用
            return False

    def _stop(self) -> None:
        if self._cdp:
            # CDP：只断开连接，不关用户浏览器
            try:
                if self._pw is not None:
                    self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        else:
            try:
                if self._context is not None:
                    self._context.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                if self._pw is not None:
                    self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
        self._context = None
        self._pw = None
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    # -- 对外 --------------------------------------------------------

    @contextmanager
    def session(self, headless: bool | None = None) -> Iterator[BrowserContext]:
        """进入：拿锁 + 确保浏览器启动；退出：关闭并释放锁。

        persistent 模式用 profile 锁（与登录窗口互斥）；
        CDP 模式用全局锁（防多进程并发连同一浏览器）。
        """
        if get_mode() == "cdp" and get_cdp_url():
            lock_path = "/tmp/tutor-cdp.lock"
        else:
            lock_path = profile_dir() + ".lock"
        self._lock = ProfileLock(lock_path, timeout=60.0)
        self._lock.acquire()
        try:
            if not self._alive():
                mode = get_headless() if headless is None else headless
                self._launch(mode)
            yield self._context
        finally:
            self._stop()

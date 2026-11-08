"""选择器驱动：用平台配置的选择器操作页面（提问 / 等回答 / 续聊 / 登录检测）。

所有选择器/行为差异都来自 Provider（配置数据），代码通用。
行为特殊平台可继承覆写（注册表在 ask 里按 key 挂载）。
"""

from __future__ import annotations

import random
import re
import time

from playwright.sync_api import Locator, Page

from tutor.config import Provider

TYPING_MAX_LEN = 40  # 短于此逐字符输入（拟人），超过 fill（模拟粘贴）
TYPING_DELAY = (30, 80)  # 逐字符延迟范围（毫秒）
STABLE_ROUNDS = 1  # 生成信号消失后需连续稳定轮数
FALLBACK_STABLE = 6  # 从未观测到生成信号时的稳定轮数（12s 兜底）
CAPTCHA_SELECTORS = (
    'iframe[src*="captcha" i]',
    'iframe[src*="verify" i]',
    'iframe[src*="geetest" i]',
    '[class*="captcha" i]',
    "text=安全验证",
    "text=拖动滑块",
    "text=请完成验证",
)
CAPTCHA_WAIT = 60  # 检测到验证码后额外等待秒数（供人工处理）


class CaptchaError(RuntimeError):
    """检测到安全验证（headless 下无法人工通过）。"""


class WebDriver:
    def __init__(self, page: Page, provider: Provider, headless: bool = False) -> None:
        self.page = page
        self.p = provider
        self.headless = headless

    # -- 输入框 --------------------------------------------------------

    def pick_input(self) -> Locator | None:
        """选输入框：优先平台配置，其次通用回退；多选时按面积取最大。"""
        sels = [s for s in (self.p.input_selector, '[contenteditable="true"]',
                            '[role="textbox"]', "textarea") if s]
        seen: set[str] = set()
        for sel in sels:
            if sel in seen:
                continue
            seen.add(sel)
            loc = self.page.locator(sel)
            if loc.count() == 0:
                continue
            if self.p.pick_largest_input and loc.count() > 1:
                return self._largest(loc)
            return loc.first
        return None

    def _largest(self, loc: Locator) -> Locator:
        best, area = 0, -1
        for i in range(loc.count()):
            box = loc.nth(i).evaluate(
                "el => {const r = el.getBoundingClientRect(); return r.width * r.height}"
            )
            if box > area:
                best, area = i, box
        return loc.nth(best)

    # -- 会话操作 ------------------------------------------------------

    def new_chat(self) -> None:
        """开启新会话：优先点「新对话」，失败用快捷键。"""
        if not self.p.open_new_chat:
            return
        try:
            btn = self.page.get_by_text(self.p.new_chat_button_text, exact=True).first
            if btn.count() > 0:
                btn.click()
                self.page.wait_for_timeout(2000)
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            self.page.keyboard.press(self.p.new_chat_shortcut)
            self.page.wait_for_timeout(2000)
        except Exception:  # noqa: BLE001
            pass

    def send(self, text: str) -> None:
        """填框并发送（有发送按钮则点，否则回车）。短文本逐字符（拟人），长文本 fill。"""
        box = self.pick_input()
        if box is None:
            raise RuntimeError("未找到聊天输入框（请确认已登录/页面已就绪）")
        box.click()
        if len(text) <= TYPING_MAX_LEN:
            box.press_sequentially(text, delay=random.randint(*TYPING_DELAY))
        else:
            box.fill(text)
        if self.p.send_selector:
            btn = self.page.locator(self.p.send_selector).first
            btn.click()
        else:
            self.page.keyboard.press("Enter")

    def resume(self, cid: str) -> None:
        """续聊：跳到会话 URL 并等就绪。"""
        url = self.p.conversation_url_fmt.format(base=self.p.url.rstrip("/"), id=cid)
        self.page.goto(url, wait_until="domcontentloaded")
        if self.p.ready_selector:
            try:
                self.page.locator(self.p.ready_selector).first.wait_for(
                    state="visible", timeout=20000
                )
            except Exception:  # noqa: BLE001
                pass
        self.page.wait_for_timeout(3000)

    def current_cid(self) -> str:
        """从当前 URL 提取会话 id（站点格式不同，长轮询兜底）。"""
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            m = re.search(self.p.conversation_id_pattern, self.page.url)
            if m:
                return m.group(1)
            time.sleep(0.5)
        return ""

    # -- 完成判定 ------------------------------------------------------

    def _generating(self) -> bool:
        if not self.p.generating_selector:
            return False
        try:
            return self.page.locator(self.p.generating_selector).count() > 0
        except Exception:  # noqa: BLE001
            return False

    def _messages_text(self) -> str:
        if not self.p.message_list_selector:
            return ""
        try:
            els = self.page.locator(self.p.message_list_selector)
            if els.count() == 0:
                return ""
            txt = ""
            for i in range(els.count()):
                txt += els.nth(i).inner_text() + "\n"
            return self._normalize(txt)
        except Exception:  # noqa: BLE001
            return ""

    def _normalize(self, text: str) -> str:
        if self.p.anchor_normalize:
            return re.sub(r"\s+", " ", text).strip()
        return text

    def _detect_captcha(self) -> bool:
        for sel in CAPTCHA_SELECTORS:
            try:
                if self.page.locator(sel).count() > 0:
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _wait_captcha(self, deadline: float) -> None:
        """检测到验证码：headless 直接报错；可见模式延长时间等人工处理。"""
        if self._detect_captcha():
            if self.headless:
                raise CaptchaError("检测到安全验证（headless 模式无法人工通过）")
            # 可见模式：把等待时限再往后推 CAPTCHA_WAIT，让人工处理
            time.sleep(CAPTCHA_WAIT)

    def _extract_answer(self, text: str, prompt: str) -> str:
        """从消息列表剔除本次提问（锚点截取），保留模型回答。"""
        norm_prompt = self._normalize(prompt)
        # 回答 = 提问之后的部分（若提问仍保留在列表里）
        idx = text.find(norm_prompt)
        ans = text[idx + len(norm_prompt):] if idx >= 0 else text
        ans = ans.strip()
        if len(ans) > self.p.answer_max_len:
            ans = ans[: self.p.answer_max_len]
        return ans or text

    def wait_answer(self, prompt: str, timeout: float = 90.0) -> str:
        """轮询直到回答稳定；返回模型回答文本。"""
        deadline = time.monotonic() + timeout
        last, stable, saw_gen = "", 0, False
        while time.monotonic() < deadline:
            self._wait_captcha(deadline)
            txt = self._messages_text()
            if txt:
                gen = self._generating()
                if gen:
                    saw_gen = True
                    continue
                if txt == last:
                    stable += 1
                else:
                    stable, last = 0, txt
                need = STABLE_ROUNDS if saw_gen else (
                    self.p.fallback_stable_rounds or FALLBACK_STABLE
                )
                if stable >= need:
                    return self._extract_answer(txt, prompt)
            time.sleep(2.0)
        raise TimeoutError("等待回答超时")

    def wait_images(self, timeout: float = 180.0) -> list[str]:
        """等待生成图片，返回图片 URL 列表。"""
        deadline = time.monotonic() + timeout
        last, stable = "", 0
        while time.monotonic() < deadline:
            imgs = self._image_urls()
            if imgs:
                if imgs == last:
                    stable += 1
                else:
                    stable, last = 0, imgs
                if stable >= STABLE_ROUNDS:
                    return imgs
            time.sleep(2.0)
        raise TimeoutError("等待图片超时")

    def _image_urls(self) -> list[str]:
        try:
            imgs = self.page.eval_on_selector_all(
                "img", "els => els.map(e => e.src).filter(Boolean)"
            )
            return [u for u in imgs if re.search(self.p.image_id_pattern, u)]
        except Exception:  # noqa: BLE001
            return []

    # -- 登录检测 ------------------------------------------------------

    def check_logged_in(self) -> bool:
        """用平台配置的选择器判断是否已登录。"""
        try:
            if self.p.logged_in_selector:
                return self.page.locator(self.p.logged_in_selector).count() > 0
            if self.p.logged_out_selector:
                return self.page.locator(self.p.logged_out_selector).count() == 0
        except Exception:  # noqa: BLE001
            return False
        return False

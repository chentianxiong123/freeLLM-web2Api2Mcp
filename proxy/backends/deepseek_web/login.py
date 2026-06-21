"""DeepSeek 登录与会话管理

处理：凭证登录、Token 刷新、会话创建
"""

import secrets

from curl_cffi import requests as cffi_requests

import config
import session as sess

# ── 常量 ────────────────────────────────────────────────

DS_BASE = "https://chat.deepseek.com"
DS_HEADERS = {
    "content-type": "application/json",
    "origin": DS_BASE,
    "referer": f"{DS_BASE}/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "x-client-version": "2.0.2",
    "x-client-platform": "web",
}


# ── 登录 ──────────────────────────────────────────────


def login(login_type: str, account: str, password: str) -> dict | None:
    """登录 DeepSeek，获取 token 并创建会话。"""

    # 构造登录 payload（参考原版 proxy.py）
    login_payload = {"password": password, "device_id": secrets.token_hex(16), "os": "web"}

    if login_type == "email":
        login_payload["email"] = account
        login_payload["mobile"] = ""
        login_payload["area_code"] = ""
    else:
        login_payload["mobile"] = account
        login_payload["area_code"] = "+86"
        login_payload["email"] = ""

    try:
        # 0. 创建 Session + 预访问首页获取 WAF Cookie
        session = cffi_requests.Session()
        session.impersonate = "chrome120"
        try:
            session.get(
                "https://chat.deepseek.com/",
                headers={"user-agent": DS_HEADERS.get("user-agent", "")},
                timeout=15,
            )
        except Exception:
            pass  # 首页访问失败不阻塞登录

        # 1. 登录（使用 session 自动携带 Cookie）
        login_resp = session.post(
            f"{DS_BASE}/api/v0/users/login",
            json=login_payload,
            headers=DS_HEADERS,
            timeout=30,
        )

        # WAF 挑战检测
        if login_resp.status_code == 202 and login_resp.headers.get("x-amzn-waf-action"):
            print("[Login] Blocked by AWS WAF (202)")
            return {"ok": False, "error": "被 AWS WAF 拦截，请配置代理"}

        raw_text = (login_resp.text or "").strip()
        if not raw_text:
            print(f"[Login] Empty response (HTTP {login_resp.status_code})")
            return None

        try:
            login_data = login_resp.json()
        except Exception:
            print(f"[Login] Non-JSON response (HTTP {login_resp.status_code}): {raw_text[:200]}")
            return None

        outer_code = login_data.get("code", 0)
        data_block = login_data.get("data") or {}
        biz_code = data_block.get("biz_code", 0)
        biz_msg = data_block.get("biz_msg", "")

        if login_resp.status_code != 200 or outer_code != 0 or biz_code != 0:
            err_msg = biz_msg or login_data.get("msg") or f"HTTP {login_resp.status_code}/code={outer_code}"
            print(f"[Login] Failed: {err_msg}")
            return None

        biz_data = data_block.get("biz_data") or {}
        token = biz_data.get("user", {}).get("token", "")
        if not token:
            print(f"[Login] No token in biz_data (biz_msg={biz_msg})")
            return None

        print(f"[Login] Token acquired: {token[:20]}...{token[-8:]}")

        # 2. 创建会话（也用 session 保持一致性）
        auth_headers = {**DS_HEADERS, "authorization": f"Bearer {token}"}
        session_resp = session.post(
            f"{DS_BASE}/api/v0/chat_session/create",
            json={},
            headers=auth_headers,
            timeout=15,
        )

        session_id = ""
        if session_resp.status_code == 200:
            session_data = session_resp.json()
            biz = session_data.get("data", {}).get("biz_data", {})
            session_id = (
                biz.get("chat_session", {}).get("id", "")
                or biz.get("id", "")
            )
            print(f"[Login] Session created: {session_id[:16]}...")
        else:
            print(f"[Login] Session creation failed: {session_resp.status_code}")

        cfg = {
            "token": token,
            "session_id": session_id or "",
            "headers": {**DS_HEADERS, "authorization": f"Bearer {token}"},
            "cookie": "",
            "login_type": login_type,
            "_password": password,
            "_email": account if login_type == "email" else "",
            "_mobile": account if login_type == "phone" else "",
        }
        config.save_config(cfg)
        if session_id:
            sess.on_new_session(session_id)
        return cfg

    except Exception as e:
        print(f"[Login] Exception: {e}")
    return None


def relogin(cfg: dict) -> dict | None:
    """用保存的密码重新登录（Token 过期时调用）。"""
    login_type = cfg.get("login_type", "")
    password = cfg.get("_password", "")
    if not password:
        print("[Relogin] No saved password, cannot auto-relogin")
        return None

    account = cfg.get("_email", "") or cfg.get("_mobile", "")
    if not account:
        print("[Relogin] No saved account")
        return None

    print("[Relogin] Attempting auto-relogin...")
    return login(login_type, account, password)

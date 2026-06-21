"""PoW（Proof of Work）求解封装

适配自 deepseek-free-api/proxy.py 的 get_pow_response 函数。
"""

from curl_cffi import requests as cffi_requests
from .pow_native import DeepSeekPOW

_solver = DeepSeekPOW()


def build_request_headers(cfg: dict, session_id: str) -> dict:
    """构建 DeepSeek API 请求头，排除过时的 PoW 和冲突头。"""
    req_headers = dict(cfg.get("headers", {}))
    req_headers.pop("x-ds-pow-response", None)
    for h in ("host", "content-length", "transfer-encoding",
              "accept-encoding", "content-type"):
        req_headers.pop(h, None)
    req_headers["content-type"] = "application/json"
    req_headers["origin"] = "https://chat.deepseek.com"
    req_headers["referer"] = f"https://chat.deepseek.com/a/chat/s/{session_id}"
    return req_headers


def get_pow_response(cfg: dict,
                     target_path: str = "/api/v0/chat/completion",
                     session_id: str | None = None) -> str | None:
    """获取并求解 PoW challenge。

    流程：
    1. POST /api/v0/chat/create_pow_challenge 获取 challenge
    2. 用 Node.js WASM（或 Python 回退）求解
    3. 返回 base64 编码的 PoW response
    """
    sid = session_id or cfg.get("session_id", "")
    headers = build_request_headers(cfg, sid)

    try:
        resp = cffi_requests.post(
            "https://chat.deepseek.com/api/v0/chat/create_pow_challenge",
            headers=headers,
            json={"target_path": target_path},
            impersonate="chrome120",
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            challenge = (
                data.get("data", {})
                    .get("biz_data", {})
                    .get("challenge", {})
            )
            if challenge:
                pow_response = _solver.solve_challenge(challenge)
                print(f"[PoW] Solved: {pow_response[:50]}...")
                return pow_response
            else:
                print(f"[PoW] No challenge in response: {data}")
        else:
            print(f"[PoW] Request failed {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[PoW] Error: {e}")
    return None

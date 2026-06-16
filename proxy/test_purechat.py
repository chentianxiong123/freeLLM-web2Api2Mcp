"""最简单的纯聊天测试，没有工具定义"""
import config
from pow import get_pow_response, build_request_headers
from curl_cffi import requests as cffi_requests
import json

cfg = config.load_config()

pow_resp = get_pow_response(cfg, session_id=cfg["session_id"])
headers = build_request_headers(cfg, cfg["session_id"])
if pow_resp: headers["x-ds-pow-response"] = pow_resp

resp = cffi_requests.post(
    "https://chat.deepseek.com/api/v0/chat/completion",
    headers=headers,
    json={
        "chat_session_id": cfg["session_id"],
        "parent_message_id": None,
        "prompt": "你好，今天天气怎么样？",
        "ref_file_ids": [],
        "thinking_enabled": False,
        "search_enabled": False,
        "model_type": "default",
    },
    impersonate="chrome120",
    stream=True,
    timeout=30,
)

print(f"状态码: {resp.status_code}")
print(f"Content-Type: {resp.headers.get('content-type', '')}")
print()

count = 0
for raw in resp.iter_lines():
    if not raw: continue
    line = raw.decode("utf-8", errors="replace").strip()
    if line: print(f"[{count}] {line[:300]}")
    count += 1
    if count > 30: break
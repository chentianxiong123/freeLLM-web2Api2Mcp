"""调试：看 chat_completion 实际 HTTP 状态"""
import config
from curl_cffi import requests as cffi_requests
from pow import get_pow_response, build_request_headers

cfg = config.load_config()
session_id = cfg["session_id"]

pow_resp = get_pow_response(cfg, session_id=session_id)
headers = build_request_headers(cfg, session_id)
if pow_resp:
    headers["x-ds-pow-response"] = pow_resp

req_body = {
    "chat_session_id": session_id,
    "parent_message_id": None,
    "prompt": "你好",
    "ref_file_ids": [],
    "thinking_enabled": False,
    "search_enabled": False,
    "model_type": "default",
}

resp = cffi_requests.post(
    "https://chat.deepseek.com/api/v0/chat/completion",
    headers=headers,
    json=req_body,
    impersonate="chrome120",
    stream=True,
    timeout=30,
)

print(f"状态码: {resp.status_code}")
print(f"Content-Type: {resp.headers.get('content-type', '')}")
print()

# 打印前 20 行原始响应
for i, raw_line in enumerate(resp.iter_lines()):
    if not raw_line:
        continue
    line = raw_line.decode("utf-8", errors="replace").strip()
    if line:
        print(f"  [{i}] {line[:200]}")
    if i > 30:
        break

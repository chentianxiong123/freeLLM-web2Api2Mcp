"""抓真实 SSE 流原始内容到文件，分析每行结构。"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg_mod
from pow import get_pow_response, build_request_headers
from curl_cffi import requests as cffi_requests

DS_BASE = "https://chat.deepseek.com"


def main():
    cfg = cfg_mod.load_config()
    sid = cfg["session_id"]
    print(f"使用 session: {sid}")

    pow_resp = get_pow_response(cfg, session_id=sid)
    if not pow_resp:
        print("PoW 失败")
        return

    headers = build_request_headers(cfg, sid)
    headers["x-ds-pow-response"] = pow_resp

    body = {
        "chat_session_id": sid,
        "parent_message_id": None,
        "prompt": "说一个简短的笑话，3句话以内。",
        "ref_file_ids": [],
        "thinking_enabled": False,
        "search_enabled": False,
        "model_type": "default",
    }

    print(f"POST /api/v0/chat/completion ...")
    t0 = time.time()
    resp = cffi_requests.post(
        f"{DS_BASE}/api/v0/chat/completion",
        headers=headers,
        json=body,
        impersonate="chrome120",
        stream=True,
        timeout=120,
    )
    print(f"HTTP {resp.status_code} ({time.time() - t0:.1f}s)")

    raw = b""
    for chunk in resp.iter_content(chunk_size=4096):
        if chunk:
            raw += chunk
    text = raw.decode("utf-8", errors="replace")

    # 写到文件，方便分析
    out = Path(__file__).parent / "_last_raw_sse.txt"
    out.write_text(text, encoding="utf-8")
    print(f"原始 SSE 写入: {out} ({len(text)} chars, {len(text.splitlines())} lines)")

    # 行类型统计
    line_types: dict[str, int] = {}
    for line in text.splitlines():
        if not line.strip():
            line_types["<空行>"] = line_types.get("<空行>", 0) + 1
        elif line.startswith("data:"):
            payload = line[5:].strip()
            if payload == "[DONE]":
                line_types["[DONE]"] = line_types.get("[DONE]", 0) + 1
            else:
                try:
                    import json as _json
                    obj = _json.loads(payload)
                    if isinstance(obj, dict):
                        key = f"path={obj.get('p', '<no p>')!r}"
                        line_types[key] = line_types.get(key, 0) + 1
                except Exception:
                    line_types["<非JSON>"] = line_types.get("<非JSON>", 0) + 1
        else:
            line_types[f"<other: {line[:20]}>"] = line_types.get(f"<other: {line[:20]}>", 0) + 1

    print("\n=== 行类型统计 ===")
    for k, v in sorted(line_types.items(), key=lambda x: -x[1]):
        print(f"  {v:4d}  {k}")


if __name__ == "__main__":
    main()

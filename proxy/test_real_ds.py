"""真实 DeepSeek 端测试 + OpenAI JSON 装换

不走代理，直接调 chat.deepseek.com/api/v0/chat/completion
- 用 deepseek_api.parse_sse 解析（已正确处理裸 v 行）
- 把结果装成 OpenAI Chat Completions 格式（非流式 + 流式）
- 验证：完整 content 能抓回来 + 续接可行

⚠️ 慢节奏：脚本只发 2 条，不会刷量。
"""

import json
import sys
import time
import uuid
from pathlib import Path

from curl_cffi import requests as cffi_requests

sys.path.insert(0, str(Path(__file__).parent))
import config as cfg_mod  # noqa: E402
from pow import get_pow_response, build_request_headers  # noqa: E402
from deepseek_api import parse_sse, create_new_session  # noqa: E402

DS_BASE = "https://chat.deepseek.com"
DS_MODEL = "deepseek-v3"


def _send_one(cfg: dict, prompt: str, parent_message_id) -> dict:
    """发一条消息到真实 DeepSeek，返回 OpenAI Chat Completions 格式（非流式）。"""
    session_id = cfg["session_id"]
    pow_resp = get_pow_response(cfg, session_id=session_id)
    if not pow_resp:
        raise RuntimeError("PoW 求解失败")

    headers = build_request_headers(cfg, session_id)
    headers["x-ds-pow-response"] = pow_resp

    body = {
        "chat_session_id": session_id,
        "parent_message_id": parent_message_id,
        "prompt": prompt,
        "ref_file_ids": [],
        "thinking_enabled": True,
        "search_enabled": False,
        "model_type": "default",
    }

    print(f"\n>>> POST /api/v0/chat/completion")
    print(f"    session_id        = {session_id}")
    print(f"    parent_message_id = {parent_message_id!r}")
    print(f"    prompt            = {prompt!r}")

    t0 = time.time()
    resp = cffi_requests.post(
        f"{DS_BASE}/api/v0/chat/completion",
        headers=headers,
        json=body,
        impersonate="chrome120",
        stream=True,
        timeout=120,
    )
    print(f"<<< HTTP {resp.status_code} ({time.time() - t0:.1f}s)")

    if resp.status_code != 200:
        chunk = next(resp.iter_content(chunk_size=500), b"")
        raise RuntimeError(f"HTTP {resp.status_code}: {chunk[:300]!r}")

    # 用 parse_sse 解析（已正确处理裸 v 行）
    thinking_parts: list[str] = []
    content_parts: list[str] = []
    rid: str | None = None
    error_msg: str | None = None

    for etype, val in parse_sse(resp, thinking_enabled=True):
        if etype == "thinking" and isinstance(val, str):
            thinking_parts.append(val)
        elif etype == "content" and isinstance(val, str):
            content_parts.append(val)
        elif etype == "message_id":
            if rid is None:
                rid = val
        elif etype == "error":
            error_msg = val.get("message", "unknown") if isinstance(val, dict) else str(val)

    thinking = "".join(thinking_parts)
    content = "".join(content_parts)

    # 装成 OpenAI Chat Completions 格式
    openai_resp = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": DS_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop" if not error_msg else "stop",
                # 把 thinking 也带上（DeepSeek 专属字段，OpenAI 兼容客户端会忽略）
                "_thinking": thinking if thinking else None,
            }
        ],
        "usage": {
            "prompt_tokens": 0,      # DeepSeek 不返回 token 数
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        # DeepSeek 端回传的元信息（OpenAI 不识别但前端可视化要用）
        "_deepseek": {
            "session_id": session_id,
            "response_message_id": rid,
            "parent_message_id": parent_message_id,
            "has_error": error_msg is not None,
            "error_message": error_msg,
        },
    }
    return openai_resp


def _send_stream(cfg: dict, prompt: str, parent_message_id):
    """发一条消息，返回流式 OpenAI 格式（generator）。"""
    session_id = cfg["session_id"]
    pow_resp = get_pow_response(cfg, session_id=session_id)
    if not pow_resp:
        raise RuntimeError("PoW 求解失败")

    headers = build_request_headers(cfg, session_id)
    headers["x-ds-pow-response"] = pow_resp

    body = {
        "chat_session_id": session_id,
        "parent_message_id": parent_message_id,
        "prompt": prompt,
        "ref_file_ids": [],
        "thinking_enabled": True,
        "search_enabled": False,
        "model_type": "default",
    }

    resp = cffi_requests.post(
        f"{DS_BASE}/api/v0/chat/completion",
        headers=headers,
        json=body,
        impersonate="chrome120",
        stream=True,
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    # 第一个 chunk：role
    yield {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": DS_MODEL,
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "content": ""},
            "finish_reason": None,
        }],
    }

    for etype, val in parse_sse(resp, thinking_enabled=True):
        if etype == "thinking" and isinstance(val, str) and val:
            yield {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": DS_MODEL,
                "choices": [{
                    "index": 0,
                    "delta": {"_thinking": val},  # 私有字段
                    "finish_reason": None,
                }],
            }
        elif etype == "content" and isinstance(val, str) and val:
            yield {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": DS_MODEL,
                "choices": [{
                    "index": 0,
                    "delta": {"content": val},
                    "finish_reason": None,
                }],
            }
        elif etype == "error":
            err = val.get("message", "unknown") if isinstance(val, dict) else str(val)
            yield {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": DS_MODEL,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
                "_error": err,
            }
            return

    # 最后一个 chunk：finish_reason
    yield {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": DS_MODEL,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop",
        }],
    }
    yield "[DONE]"


def main():
    cfg = cfg_mod.load_config()
    if not cfg.get("token"):
        print("config.json 缺 token")
        sys.exit(1)

    # 每次都建新 session（不重用，避免污染历史）
    # 注意：不写入 config.json，跑完就走，不影响代理默认 session
    print("[准备] 创建全新 session...")
    new_sid = create_new_session(cfg)
    if not new_sid:
        print("❌ 建 session 失败")
        sys.exit(1)
    # 只在内存里用，不持久化
    cfg = {**cfg, "session_id": new_sid}
    print(f"[准备] 新 session_id = {new_sid}（不写入 config.json）")

    print(f"=== 真实 DeepSeek → OpenAI JSON 装换测试 ===")
    print(f"session_id = {cfg['session_id']}")

    # ===== 第 1 条：根消息 =====
    prompt1 = "说一个简短的笑话，3句话以内。"
    print(f"\n[1/2] 发第 1 条: {prompt1!r}")
    r1 = _send_one(cfg, prompt1, None)
    print(f"\n--- 第 1 条 OpenAI 格式 ---")
    print(json.dumps(r1, ensure_ascii=False, indent=2))
    rid1 = r1["_deepseek"]["response_message_id"]
    if not rid1:
        print("\n❌ 没抓到 response_message_id")
        sys.exit(1)

    print(f"\n[等待 10 秒再发第 2 条]")
    time.sleep(10)

    # ===== 第 2 条：续接 =====
    prompt2 = "再讲一个，但是这个要可爱一点。"
    print(f"\n[2/2] 发第 2 条: {prompt2!r} (parent={rid1})")
    r2 = _send_one(cfg, prompt2, int(rid1))
    print(f"\n--- 第 2 条 OpenAI 格式 ---")
    print(json.dumps(r2, ensure_ascii=False, indent=2))
    rid2 = r2["_deepseek"]["response_message_id"]

    print(f"\n=== 总结 ===")
    print(f"  第 1 条: parent=null        → response_message_id={rid1}")
    print(f"  第 2 条: parent={rid1:>3}        → response_message_id={rid2}")
    print(f"  完整 content 第 1 条: {r1['choices'][0]['message']['content'][:60]!r}{'...' if len(r1['choices'][0]['message']['content']) > 60 else ''}")
    print(f"  完整 content 第 2 条: {r2['choices'][0]['message']['content'][:60]!r}{'...' if len(r2['choices'][0]['message']['content']) > 60 else ''}")

    # ===== 测一次流式 =====
    print(f"\n[3/3] 测流式输出（独立请求，parent={rid2}）...")
    print(f"[等待 10 秒]")
    time.sleep(10)
    prompt3 = "上面那个笑话的笑点是什么？一句话回答。"

    print(f"\n>>> 流式输出 chunks（模拟 OpenAI SSE）:")
    for i, chunk in enumerate(_send_stream(cfg, prompt3, int(rid2))):
        if chunk == "[DONE]":
            print(f"  chunk {i}: [DONE]")
        else:
            d = chunk["choices"][0]["delta"]
            content_piece = d.get("content", "")
            thinking_piece = d.get("_thinking", "")
            if content_piece:
                print(f"  chunk {i}: content={content_piece!r}")
            elif thinking_piece:
                print(f"  chunk {i}: thinking={thinking_piece!r}")
            elif d.get("role") == "assistant":
                print(f"  chunk {i}: role=assistant")
            elif chunk["choices"][0].get("finish_reason"):
                print(f"  chunk {i}: finish_reason={chunk['choices'][0]['finish_reason']}")

    print(f"\n=== 流式测试结束 ===")


if __name__ == "__main__":
    main()

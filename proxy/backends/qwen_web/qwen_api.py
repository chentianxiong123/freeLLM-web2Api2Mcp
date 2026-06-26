"""Qwen (chat.qwen.ai) 网页端 API 底层调用。

协议（参考 qwen2API Node.js 项目）：
  - 认证：Authorization: Bearer <JWT token> + Cookie: token=<JWT token>
  - 创建会话：POST /api/v2/chats/new
  - 流式对话：POST /api/v2/chat/completions?chat_id=<id>
  - 删除会话：DELETE /api/v2/chats/<id>
  - SSE 格式：标准 data: 行，choices[0].delta.{content, reasoning_content, phase, status}

关键：必须完全复刻 Node.js 的请求头才能绕过 WAF。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any

import httpx

BASE_URL = "https://chat.qwen.ai"

_qwen_lock = threading.Lock()


def _headers(token: str) -> dict[str, str]:
    """完全复刻 Node.js Qwen2API 的请求头。"""
    return {
        "sec-ch-ua-platform": '"Windows"',
        "authorization": f"Bearer {token}",
        "referer": f"{BASE_URL}/",
        "accept-language": "zh-CN,zh;q=0.9",
        "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "content-type": "application/json",
        "bx-v": "2.5.36",
        "accept": "text/event-stream",
        # 不发送 accept-encoding，避免 Brotli 压缩导致 httpx 无法解码
        "source": "web",
        "version": "0.2.63",
        "timezone": "Mon Jun 22 2026 12:00:00 GMT+0800 (China Standard Time)",
        "x-request-id": uuid.uuid4().hex,
        "connection": "keep-alive",
        "cookie": f"token={token}",
        "host": "chat.qwen.ai",
        "origin": BASE_URL,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-accel-buffering": "no",
    }


def _rand_id() -> str:
    return os.urandom(16).hex()


def create_chat(token: str, model: str) -> str | None:
    """创建 Qwen 会话，返回 chat_id。"""
    body = {
        "title": f"api_{int(time.time())}",
        "models": [model],
        "chat_mode": "normal",
        "chat_type": "t2t",
        "timestamp": int(time.time()),
    }
    try:
        resp = httpx.post(
            f"{BASE_URL}/api/v2/chats/new",
            json=body,
            headers=_headers(token),
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") is False:
                return None
            chat_id = (data.get("data") or {}).get("id", "")
            if chat_id:
                print(f"[Qwen] Created chat: {chat_id[:12]}...")
                return chat_id
        else:
            print(f"[Qwen] Create chat failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[Qwen] Create chat error: {e}")
    return None


def get_chat_history(token: str, chat_id: str) -> list[dict] | None:
    """获取会话历史消息列表（按时间排序）。"""
    try:
        resp = httpx.get(
            f"{BASE_URL}/api/v2/chats/{chat_id}",
            headers=_headers(token),
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data.get("success"):
            return None
        msgs_dict = (
            (data.get("data") or {})
            .get("chat", {})
            .get("history", {})
            .get("messages", {})
        )
        msgs = list(msgs_dict.values())
        # 按时间排序
        msgs.sort(key=lambda m: m.get("timestamp", 0))
        # 对 assistant 消息，从 content_list 补充 content
        for m in msgs:
            if m.get("role") == "assistant":
                cl = m.get("content_list") or []
                if cl and not m.get("content"):
                    m["content"] = cl[0].get("content", "")
        return msgs
    except Exception as e:
        print(f"[Qwen] Get history error: {e}")
    return None


def delete_chat(token: str, chat_id: str) -> bool:
    """删除 Qwen 会话。"""
    try:
        resp = httpx.delete(
            f"{BASE_URL}/api/v2/chats/{chat_id}",
            headers=_headers(token),
            timeout=20,
        )
        return resp.status_code in (200, 204, 404)
    except Exception:
        return False


# ── thinking 标签解析状态机 ──────────────────────────────
_TAG_OPEN = "<think>"
_TAG_CLOSE = "</think>"


class _ThinkingParser:
    """流式解析 <think>...</think> 标签，分离 reasoning 和 answer。"""

    def __init__(self):
        self._buf = ""
        self._in_thinking = False

    def feed(self, text: str) -> tuple[str, str]:
        self._buf += text
        thinking = ""
        answer = ""
        while self._buf:
            if self._in_thinking:
                close_idx = self._buf.find(_TAG_CLOSE)
                if close_idx == -1:
                    thinking += self._buf
                    self._buf = ""
                else:
                    thinking += self._buf[:close_idx]
                    self._buf = self._buf[close_idx + len(_TAG_CLOSE):]
                    self._in_thinking = False
            else:
                open_idx = self._buf.find(_TAG_OPEN)
                if open_idx == -1:
                    answer += self._buf
                    self._buf = ""
                else:
                    answer += self._buf[:open_idx]
                    self._buf = self._buf[open_idx + len(_TAG_OPEN):]
                    self._in_thinking = True
        return thinking, answer


# ── 续接缓存 ────────────────────────────────────
_last_response_message_id: dict[str, str] = {}

def get_last_message_id(chat_id: str) -> str | None:
    """获取续接点，优先从内存缓存，其次从 sessions.json。"""
    mid = _last_response_message_id.get(chat_id)
    if mid:
        return mid
    # 从 sessions.json 恢复
    try:
        import session as sess
        db = sess._load()
        s = db.get("sessions", {}).get(chat_id, {})
        mid = s.get("last_message_id")
        if mid:
            _last_response_message_id[chat_id] = str(mid)
            return str(mid)
    except Exception:
        pass
    return None

def reset_last_message_id(chat_id: str | None = None) -> None:
    global _last_response_message_id
    if chat_id is None:
        _last_response_message_id = {}
    else:
        _last_response_message_id.pop(chat_id, None)


def chat_completion(
    token: str,
    chat_id: str,
    model: str,
    messages: list[dict],
    *,
    thinking_enabled: bool = True,
    search_enabled: bool = False,
    has_tools: bool = False,
    parent_id: str | None = None,
) -> Any:
    """发送流式聊天请求到 Qwen。

    parent_id: 续接已有会话时，传上一条 assistant 消息的 id，否则传 None（新会话）。
    产出包含 ("message_id", str) 和 ("usage", dict) 事件。
    """

    _qwen_lock.acquire()
    try:
        feature_config = {
            "thinking_enabled": thinking_enabled,
            "output_schema": "phase",
            "research_mode": "normal",
            "auto_thinking": thinking_enabled,
            "thinking_mode": "Auto" if thinking_enabled else "Disabled",
            "thinking_format": "summary",
            "auto_search": search_enabled,
            "code_interpreter": False,
            "plugins_enabled": False,
            "function_calling": has_tools,
            "enable_tools": has_tools,
            "enable_function_call": has_tools,
            "tool_choice": "auto" if has_tools else "none",
        }

        content = ""
        sys_content = ""
        for m in messages:
            if m.get("role") == "system":
                sys_content = m["content"]
            elif m.get("role") == "user":
                content = m.get("content", "")
        if sys_content and content:
            content = f"{sys_content}\n\n{content}"
        elif sys_content and not content:
            content = sys_content

        fid = _rand_id()
        child_id = _rand_id()
        ts = int(time.time())
        msg = {
            "fid": fid,
            "parentId": parent_id,
            "childrenIds": [child_id],
            "role": "user",
            "content": content,
            "user_action": "chat",
            "files": [],
            "timestamp": ts,
            "models": [model],
            "chat_type": "t2t",
            "feature_config": feature_config,
            "extra": {"meta": {"subChatType": "t2t"}},
            "sub_chat_type": "t2t",
            "parent_id": parent_id,
        }

        req_body = {
            "stream": True,
            "version": "2.1",
            "incremental_output": True,
            "chat_id": chat_id,
            "chat_mode": "normal",
            "model": model,
            "parent_id": parent_id,
            "messages": [msg],
            "timestamp": ts,
        }

        hdrs = _headers(token)
        parser = _ThinkingParser()
        sent_content_len = 0
        sent_thinking_len = 0
        response_id = None
        usage_data = None

        with httpx.Client(timeout=120) as client:
            with client.stream(
                "POST",
                f"{BASE_URL}/api/v2/chat/completions?chat_id={chat_id}",
                json=req_body,
                headers=hdrs,
            ) as resp:
                if resp.status_code != 200:
                    error_msg = f"Qwen returned {resp.status_code}"
                    try:
                        chunk = next(resp.iter_bytes(chunk_size=500), b"")
                        if chunk:
                            error_msg += f": {chunk.decode('utf-8', errors='replace')[:300]}"
                    except Exception:
                        pass
                    yield ("error", {"message": error_msg})
                    return

                buf = b""
                pending_tool_calls: dict[int, dict] = {}
                accum_content = ""
                accum_thinking = ""
                had_content = False
                had_empty_after_content = False
                for chunk in resp.iter_bytes(chunk_size=4096):
                    if not chunk:
                        continue
                    buf += chunk
                    while b"\n" in buf:
                        raw_line, buf = buf.split(b"\n", 1)
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data: "):
                            # 非 SSE 行：检查是否为 Qwen 错误响应
                            if any(kw in line for kw in ("FAIL_SYS", "RGV587_ERROR", '"ret"')):
                                yield ("error", {"message": f"Qwen API 风控错误: {line[:300]}"})
                                return
                            if '"success":false' in line:
                                yield ("error", {"message": f"Qwen API 返回失败: {line[:300]}"})
                                return
                            continue
                        payload = line[6:]
                        if payload == "[DONE]":
                            yield from _finish_stream(accum_content, sent_content_len, accum_thinking, sent_thinking_len, response_id, usage_data, chat_id)
                            return
                        parsed = _parse_sse_line(payload)
                        if parsed is None:
                            continue
                        # 捕获 response_id（从第二帧起的顶层字段）
                        rid = parsed.get("response_id")
                        if rid and not response_id:
                            response_id = rid
                        u = parsed.get("usage")
                        if u:
                            usage_data = u
                        tcs = parsed.get("tool_calls")
                        if tcs:
                            for tc in tcs:
                                idx = tc.get("index", 0)
                                name = tc.get("name", "")
                                args = tc.get("arguments", "")
                                if idx not in pending_tool_calls:
                                    pending_tool_calls[idx] = {"name": name, "arguments": args}
                                else:
                                    if name:
                                        pending_tool_calls[idx]["name"] = name
                                    if args:
                                        pending_tool_calls[idx]["arguments"] += args
                        raw_content = parsed.get("content", "")
                        raw_reasoning = parsed.get("reasoning", "")
                        if raw_reasoning:
                            if raw_reasoning.startswith(accum_thinking):
                                accum_thinking = raw_reasoning
                            elif accum_thinking and raw_reasoning in accum_thinking:
                                pass
                            else:
                                extra = raw_reasoning[len(accum_thinking):] if accum_thinking and accum_thinking.endswith(raw_reasoning[:min(20, len(accum_thinking))]) else raw_reasoning
                                accum_thinking += extra
                            if len(accum_thinking) > sent_thinking_len:
                                yield ("thinking", accum_thinking[sent_thinking_len:])
                                sent_thinking_len = len(accum_thinking)
                        if raw_content:
                            had_content = True
                            if raw_content.startswith(accum_content):
                                accum_content = raw_content
                            elif accum_content and raw_content in accum_content:
                                pass
                            else:
                                accum_content += raw_content
                            if len(accum_content) > sent_content_len:
                                yield ("content", accum_content[sent_content_len:])
                                sent_content_len = len(accum_content)
                        else:
                            if had_content:
                                had_empty_after_content = True
                        if parsed.get("finish_reason") == "stop":
                            for tc in pending_tool_calls.values():
                                if tc["name"] or tc["arguments"]:
                                    yield ("tool_call", tc)
                            pending_tool_calls.clear()
                            yield from _finish_stream(accum_content, sent_content_len, accum_thinking, sent_thinking_len, response_id, usage_data, chat_id)
                            return
                # 流结束：没有 [DONE] 或 finish_reason，但有数据 → 正常结束
                yield from _finish_stream(accum_content, sent_content_len, accum_thinking, sent_thinking_len, response_id, usage_data, chat_id)

    except Exception as e:
        print(f"[Qwen] Exception: {e}")
        yield ("error", {"message": str(e)})
    finally:
        _qwen_lock.release()


def _finish_stream(accum_content, sent_content_len, accum_thinking, sent_thinking_len, response_id, usage_data, chat_id):
    """flush 剩余 content/thinking，然后 yield message_id + usage + done。"""
    if accum_content:
        diff = accum_content[sent_content_len:]
        if diff:
            yield ("content", diff)
    if accum_thinking:
        diff = accum_thinking[sent_thinking_len:]
        if diff:
            yield ("thinking", diff)
    if response_id:
        _last_response_message_id[chat_id] = response_id
        yield ("message_id", response_id)
    if usage_data:
        yield ("usage", usage_data)
    yield ("done", None)


def _parse_sse_line(data: str) -> dict | None:
    """解析单条 data: JSON 行。

    返回 dict 包含：
      - response_id: str | None
      - usage: dict | None
      - content: str
      - reasoning: str
      - finish_reason: str
      - tool_calls: list | None
      - created: dict | None  (第一帧 response.created)
    """
    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return None

    result: dict = {
        "response_id": obj.get("response_id"),
        "usage": obj.get("usage"),
        "created": obj.get("response.created"),
        "content": "",
        "reasoning": "",
        "finish_reason": "",
        "tool_calls": None,
    }

    # 第一帧特殊结构：{"response.created": {"response_id": ..., "parent_id": ...}}
    created = obj.get("response.created")
    if isinstance(created, dict) and not isinstance(obj.get("choices"), list):
        rid = created.get("response_id")
        if rid:
            result["response_id"] = rid
        return result

    choices = obj.get("choices")
    if not isinstance(choices, list) or not choices:
        return result
    delta = choices[0].get("delta") or {}

    result["content"] = delta.get("content", "")
    result["reasoning"] = delta.get("reasoning_content", "")
    result["finish_reason"] = choices[0].get("finish_reason", "")

    raw_tool_calls = delta.get("tool_calls")
    if isinstance(raw_tool_calls, list) and raw_tool_calls:
        tc_list = []
        for tc in raw_tool_calls:
            func = tc.get("function") or {}
            name = func.get("name", "")
            args_raw = func.get("arguments", "")
            idx = tc.get("index", 0)
            if name or args_raw:
                tc_list.append({"index": idx, "name": name, "arguments": args_raw})
        if tc_list:
            result["tool_calls"] = tc_list

    return result

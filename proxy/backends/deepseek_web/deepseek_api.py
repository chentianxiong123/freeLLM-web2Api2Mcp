"""DeepSeek 网页端 API 底层调用

处理：会话管理、PoW、聊天请求、SSE 解析、Token 刷新
登录逻辑已移至 login.py
"""

import json
import re
import time
import uuid
from typing import Any

from curl_cffi import requests as cffi_requests

import config
import session as sess
from .pow import get_pow_response, build_request_headers
from .login import DS_BASE, DS_HEADERS

# ── SSE 解析（适配自 proxy.py _parse_sse）───────────────


def _check_biz_error(text: str) -> str | None:
    """检查 biz_code 错误"""
    try:
        data = json.loads(text)
        biz_code = data.get("data", {}).get("biz_code", 0)
        if biz_code != 0:
            return data.get("data", {}).get("biz_msg", f"biz_code={biz_code}")
    except Exception:
        pass
    return None


def parse_sse(resp, thinking_enabled: bool = False) -> Any:
    """解析 DeepSeek SSE 流，产出 (type, value) 元组。

    type: "content" | "thinking" | "error" | "done"
    适配自 deepseek-free-api/proxy.py _parse_sse
    """
    non_json_line_count = 0
    phase = "thinking"
    fragment_type = None  # None=旧格式, "THINK"/"RESPONSE"=新格式

    def _read_lines():
        buf = b""
        for chunk in resp.iter_content(chunk_size=4096):
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw_line, buf = buf.split(b"\n", 1)
                yield raw_line.decode("utf-8", errors="ignore").strip()
        if buf.strip():
            yield buf.decode("utf-8", errors="ignore").strip()

    for line in _read_lines():
        if not line:
            continue

        # 跳过 event: 行
        if line.startswith("event:"):
            continue
        # 跳过注释行
        if line.startswith(":") or line == ":":
            continue
        # 检测 HTML 错误
        if line.startswith("<!DOCTYPE") or line.startswith("<html") or line.startswith("<HTML"):
            yield ("error", {"message": f"HTML error: {line[:200]}", "code": "html_response"})
            return

        # 去掉 data: 前缀
        ds = line[6:] if line.startswith("data: ") else line
        if ds.strip() in (":", ""):
            continue
        if ds.strip() == "[DONE]":
            yield ("done", None)
            return

        try:
            obj = json.loads(ds)
            if not isinstance(obj, dict):
                continue

            # 顶层字段：SSE 第一帧会带 response_message_id / request_message_id
            # 这是 DeepSeek 给「这条回复对应的 assistant 消息」分配的 id，
            # 下次请求要把它作为 parent_message_id 才能续接。
            # 统一转 int（DeepSeek 端期望 u32）
            top_message_id = obj.get("response_message_id")
            if top_message_id is not None:
                try:
                    yield ("message_id", int(top_message_id))
                except (ValueError, TypeError):
                    pass

            # 错误对象
            obj_type = obj.get("type", "")
            if obj_type == "error":
                yield ("error", {"message": obj.get("content", ""), "code": obj.get("finish_reason", "")})
                return

            val = obj.get("v")

            # Toast error
            if isinstance(val, dict):
                t_type = val.get("type", "")
                t_content = val.get("content", "")
                fr = val.get("finish_reason", "")
                if t_type == "error" and fr:
                    yield ("error", {"message": t_content, "code": fr})
                    return
                # 新格式: response.fragments
                resp_data = val.get("response", {})
                if isinstance(resp_data, dict):
                    frags = resp_data.get("fragments", [])
                    if frags and isinstance(frags, list):
                        for frag in frags:
                            if isinstance(frag, dict):
                                ftype = frag.get("type", "")
                                if ftype:
                                    fragment_type = ftype
                                fcontent = frag.get("content", "")
                                if fcontent and isinstance(fcontent, str):
                                    if fragment_type == "THINK":
                                        yield ("thinking", fcontent)
                                    else:
                                        yield ("content", fcontent)
                continue

            path = obj.get("p", "")

            # 新格式: response/fragments APPEND
            if path == "response/fragments" and obj.get("o") == "APPEND" and isinstance(val, list):
                if val:
                    last_frag = val[-1] if isinstance(val[-1], dict) else {}
                    new_type = last_frag.get("type", "")
                    if new_type:
                        fragment_type = new_type
                    frag_content = last_frag.get("content", "")
                    if frag_content and isinstance(frag_content, str):
                        if fragment_type == "THINK":
                            yield ("thinking", frag_content)
                        else:
                            yield ("content", frag_content)
                continue

            # 片段内容: response/fragments/-1/content
            if path == "response/fragments/-1/content":
                if fragment_type == "THINK":
                    phase = "thinking"
                    if isinstance(val, str) and val:
                        yield ("thinking", val)
                else:
                    phase = "content"
                    if isinstance(val, str) and val:
                        yield ("content", val)
                continue

            # 旧格式: response/content + response/thinking_content
            if path == "response/content":
                o_val = obj.get("o")
                if o_val is None or o_val == "APPEND":
                    phase = "content"
                    if isinstance(val, str) and val:
                        yield ("content", val)
            elif path == "response/thinking_content" and thinking_enabled:
                o_val = obj.get("o")
                if o_val is None or o_val == "APPEND":
                    phase = "thinking"
                    if isinstance(val, str) and val:
                        yield ("thinking", val)

            # Token 用量（BATCH 终值，例如 [accumulated_token_usage, quasi_status]）
            if path == "response" and obj.get("o") == "BATCH" and isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and item.get("p") == "accumulated_token_usage":
                        tok = item.get("v")
                        if isinstance(tok, (int, float)) and tok:
                            yield ("token_usage", int(tok))
                continue
            # 顶层 response 详情里的 initial accumulated_token_usage（响应开始时的值，通常是 0）
            if isinstance(val, dict):
                inner = val.get("response", {})
                if isinstance(inner, dict) and "accumulated_token_usage" in inner:
                    tok = inner["accumulated_token_usage"]
                    if isinstance(tok, (int, float)) and tok:
                        yield ("token_usage", int(tok))

            elif path:
                continue  # 其他元数据
            elif isinstance(val, str) and val:
                # 无路径的行
                if fragment_type is not None:
                    if fragment_type == "THINK":
                        yield ("thinking", val)
                    else:
                        yield ("content", val)
                else:
                    if phase == "thinking" and thinking_enabled:
                        yield ("thinking", val)
                    else:
                        yield ("content", val)
        except json.JSONDecodeError:
            non_json_line_count += 1
            if non_json_line_count > 20:
                yield ("error", {"message": "too many non-JSON lines"})
                return
            continue


# ── 会话管理 ──────────────────────────────────────────


def create_new_session(cfg: dict) -> str | None:
    """创建新会话，返回 session_id。"""
    auth_headers = {**DS_HEADERS, "authorization": f"Bearer {cfg['token']}"}
    try:
        resp = cffi_requests.post(
            f"{DS_BASE}/api/v0/chat_session/create",
            json={},
            headers=auth_headers,
            impersonate="chrome120",
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            biz = data.get("data", {}).get("biz_data", {})
            session_id = (
                biz.get("chat_session", {}).get("id", "")
                or biz.get("id", "")
            )
            if session_id:
                print(f"[Session] Created: {session_id[:16]}...")
                return session_id
            else:
                print(f"[Session] Create OK but no id: {data}")
        else:
            print(f"[Session] Create failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[Session] Error: {e}")
    return None


# ── 聊天请求 ──────────────────────────────────────────────

# 按 chat_session_id 维度记录「上一次 assistant 回复的 message_id」
# 下一轮请求时把它作为 parent_message_id 传过去，让 DeepSeek 网页端的
# 「对话树」自然续接（user msg → assistant msg → user msg → assistant msg ...），
# 而不是反复创建新根消息。
_last_response_message_id: dict[str, int] = {}


def get_last_message_id(session_id: str) -> str | None:
    """查询某个 session 上一次回复的 message_id（供外部测试/调试用）。"""
    return _last_response_message_id.get(session_id)


def reset_last_message_id(session_id: str | None = None) -> None:
    """重置 message_id 缓存。

    - 传 session_id：只重置这个 session（用于「重新生成」场景）
    - 不传：清空所有（用于「开新会话」/「重启代理」场景）
    """
    global _last_response_message_id
    if session_id is None:
        _last_response_message_id = {}
    else:
        _last_response_message_id.pop(session_id, None)


def chat_completion(
    cfg: dict,
    messages: list[dict],
    model: str = "deepseek-default",
    model_type: str = "default",
    thinking_enabled: bool = True,
    search_enabled: bool = False,
    tools: list[dict] | None = None,
    stream: bool = True,
    is_retry: bool = False,
    parent_message_id: str | int | None = None,
    capture_message_id: bool = True,
) -> Any:
    """发送聊天请求到 DeepSeek。

    返回：
        stream=True  → generator of (type, value) tuples
        stream=False → dict

    关键参数：
        parent_message_id
            上一轮 assistant 回复的 message_id。
            - 传 None 或 0 → DeepSeek 创建新的根消息（= 你网页端「开始新对话」）
            - 传上次的 id  → DeepSeek 在那个消息下面续写（= 你网页端「继续聊天」）
            - 默认行为：自动从缓存里读（同一个 session 的上一次回复）

        capture_message_id
            是否把本次响应里 DeepSeek 给的 response_message_id 写进缓存。
            - True（默认）：下次同 session 的请求会自动续接
            - False：不写缓存（用于「重新生成」场景，下次会创建新根消息）
    """
    session_id = cfg.get("session_id", "")
    if not session_id:
        print("[Chat] No session_id, creating...")
        session_id = create_new_session(cfg)
        if session_id:
            sess.on_new_session(session_id, model)
            cfg = config.load_config()

    import traceback
    print(f"[DS-CALL] chat_completion ENTRY session={session_id[:8]} model={model} model_type={model_type} is_retry={is_retry}")
    print(f"[DS-CALL] caller stack:\n{''.join(traceback.format_stack()[-6:-1])}")

    # PoW
    pow_resp = get_pow_response(cfg, session_id=session_id)

    # 决定 parent_message_id
    # 优先级：调用方显式传入 > 内存缓存 > disk 持久化（session.py）
    # disk 才是「重启也不丢续接」的关键
    if parent_message_id is None:
        parent_message_id = _last_response_message_id.get(session_id)
    if parent_message_id is None:
        disk_mid = sess.get_last_message_id()
        if disk_mid:
            parent_message_id = disk_mid
    if parent_message_id in (None, 0, ""):
        # DeepSeek 端：用 null 表示「创建新根消息」
        parent_message_id = None
        print(f"[Chat] {session_id[:8]}... → NEW root message")
    else:
        # DeepSeek 端期望 u32 整数（不要字符串，否则 422）
        # 兼容 disk 里的历史字符串数据
        if isinstance(parent_message_id, str):
            try:
                parent_message_id = int(parent_message_id)
            except (ValueError, TypeError):
                parent_message_id = None
        elif not isinstance(parent_message_id, int):
            parent_message_id = None
        if parent_message_id is not None:
            print(f"[Chat] {session_id[:8]}... → CONTINUE from parent_message_id={parent_message_id} (int)")
        else:
            print(f"[Chat] {session_id[:8]}... → NEW root message (bad mid coerced to null)")

    # 构建请求体
    req_body = {
        "chat_session_id": session_id,
        "parent_message_id": parent_message_id,
        "prompt": messages[-1]["content"] if messages else "",
        "ref_file_ids": [],
        "thinking_enabled": thinking_enabled,
        "search_enabled": search_enabled,
    }

    print(f"[DS-REQ] prompt[:200]={req_body['prompt'][:200]!r} parent={parent_message_id} model_type={model_type or 'default'}")

    # model_type：DeepSeek 根据此值路由到不同模型后端
    # 优先使用调用方传入的 model_type，其次从模型名推断
    if model_type:
        req_body["model_type"] = model_type
    elif "vision" in model:
        req_body["model_type"] = "vision"
    elif "expert" in model:
        req_body["model_type"] = "expert"
    else:
        req_body["model_type"] = "default"

    # 构建请求头
    req_headers = build_request_headers(cfg, session_id)
    if pow_resp:
        req_headers["x-ds-pow-response"] = pow_resp

    try:
        resp = cffi_requests.post(
            f"{DS_BASE}/api/v0/chat/completion",
            headers=req_headers,
            json=req_body,
            impersonate="chrome120",
            stream=True,
            timeout=120,
        )

        # 401 → 自动重新登录
        if resp.status_code == 401 and not is_retry:
            print("[Chat] 401, trying relogin...")
            from .login import relogin
            new_cfg = relogin(cfg)
            if new_cfg:
                for chunk in chat_completion(
                    new_cfg, messages, model=model, model_type=model_type,
                    thinking_enabled=thinking_enabled, search_enabled=search_enabled,
                    tools=tools, stream=stream, is_retry=True,
                    parent_message_id=parent_message_id, capture_message_id=capture_message_id,
                ):
                    yield chunk
                return
            else:
                print("[Chat] Relogin failed")
                yield ("error", {"message": "Token expired and relogin failed"})
                return

        if resp.status_code != 200:
            error_msg = f"DeepSeek returned {resp.status_code}"
            try:
                chunk = next(resp.iter_content(chunk_size=500), b"")
                if chunk:
                    body = chunk.decode("utf-8", errors="replace")[:300]
                    error_msg += f": {body}"
            except Exception:
                pass
            print(f"[Chat] Error: {error_msg}")
            yield ("error", {"message": error_msg})
            return

        # 检查首个 chunk 里的 biz_code（如果有错，提前 bail）
        # 注意：只读一次，绝不替换 resp.iter_content（避免后续 generator 冲突）
        first_chunk = next(resp.iter_content(chunk_size=2000), b"")
        if first_chunk:
            text = first_chunk.decode("utf-8", errors="replace")
            biz_err = _check_biz_error(text)
            if biz_err:
                print(f"[Chat] Biz error: {biz_err}")
                yield ("error", {"message": biz_err})
                return
            # 把首个 chunk 重新喂给 parse_sse
            resp._prepend_chunk = first_chunk

        # 包一层 iter_content：开头补回首个 chunk
        original_iter_content = resp.iter_content

        def _safe_iter_content(chunk_size=None):
            if getattr(resp, "_prepend_chunk", None):
                pre = resp._prepend_chunk
                resp._prepend_chunk = None
                yield pre
            yield from original_iter_content(chunk_size=chunk_size)

        resp.iter_content = _safe_iter_content

        # 把 SSE 解析包一层：抓到 message_id 时写进缓存 + yield 给上游
        captured_id: list = []
        captured_tokens: list[int] = []  # 抓 accumulated_token_usage 终值（本次请求消耗）
        for etype, val in parse_sse(resp, thinking_enabled=thinking_enabled):
            if etype == "message_id":
                captured_id.append(val)
                if capture_message_id:
                    _last_response_message_id[session_id] = val
                    # 同步持久化到 disk（重启代理也不丢续接）
                    try:
                        sess.set_last_message_id(val)
                        sess.increment_message_count()
                        # token 用量在 react_loop 里统一按字符估算，这里不再重复加
                    except Exception as e:
                        print(f"[Chat] ⚠️ 写 disk 失败: {e}")
                    print(f"[Chat] {session_id[:8]}... captured message_id={val} (内存+disk，下次续接用)")
            elif etype == "token_usage":
                captured_tokens.append(val)
            yield (etype, val)

        if not captured_id and capture_message_id:
            print(f"[Chat] {session_id[:8]}... ⚠️ 流里没拿到 message_id，下次会被当成 NEW root")
        if not captured_tokens:
            print(f"[Chat] {session_id[:8]}... ⚠️ 流里没拿到 token_usage 字段（DeepSeek 端可能没返回）")

    except Exception as e:
        print(f"[Chat] Exception: {e}")
        yield ("error", {"message": str(e)})

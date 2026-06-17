"""请求审批队列 — 网关手动放行机制

Claude Code 发来的请求先进入队列，
管理员在网页上点"放行"才真正发给 DeepSeek。
"""

import asyncio
import copy
import json
import re
import time
from typing import Any

# 审批队列
_pending: dict[str, dict] = {}
_req_counter = 0


def enqueue(request_data: dict) -> tuple[str, asyncio.Event]:
    """将请求加入审批队列，返回 (req_id, event)。"""
    global _req_counter
    _req_counter += 1
    req_id = f"req_{_req_counter:04d}"
    event = asyncio.Event()
    _pending[req_id] = {
        "id": req_id,
        "data": request_data,
        "event": event,
        "result": None,
        "error": None,
        "created_at": time.time(),
        "status": "pending",
    }
    print(f"[审批] 新请求 {req_id} 进入队列等待审批")
    return req_id, event


def _extract_preview(data: dict) -> dict:
    """从请求数据中提取完整摘要信息。"""
    msgs = data.get("messages", [])
    system = data.get("system", "")
    model = data.get("model", "")
    stream = data.get("stream", False)

    # 清理用户真实文本的辅助（去除 Claude Code / harness 注入的各种 metadata 块）
    def _clean_text_block(t: str) -> str:
        if not isinstance(t, str):
            return ""
        pats = [
            r"<system-reminder>.*?</system-reminder>",
            r"<local-command-caveat>.*?</local-command-caveat>",
            r"<command-name>.*?</command-name>",
            r"<command-message>.*?</command-message>",
            r"<command-args>.*?</command-args>",
            r"<local-command-stdout>.*?</local-command-stdout>",
        ]
        for p in pats:
            t = re.sub(p, "", t, flags=re.DOTALL)
        t = re.sub(r"\n{3,}", "\n\n", t).strip()
        return t

    # 提取各类消息（按“只保留最新 user 消息”的展示策略过滤）
    user_msgs = []
    assistant_msgs = []
    tool_results = []
    system_prompt_len = 0

    if system:
        system_prompt_len = len(system) if isinstance(system, str) else len(str(system))
        if isinstance(system, list):
            system = "\n".join(s.get("text", "") for s in system if isinstance(s, dict))

    # 定位最后一条 user，用于只提取该条（过滤历史 user）
    last_user_idx = None
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") == "user":
            last_user_idx = i
            break

    for i, msg in enumerate(msgs):
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            if isinstance(content, str):
                system_prompt_len += len(content)
                system += "\n" + content
        elif role == "user":
            # 只处理最后一条 user 消息，其它历史 user 跳过
            if last_user_idx is not None and i != last_user_idx:
                continue
            if isinstance(content, list):
                # 关键策略：只保留这条 user 消息中“最后一个 text 块”（即用户真正输入的那一段）
                # 前面的 text 块基本都是 harness 注入的 <system-reminder> / local-command-* 等，直接丢弃
                last_text_block = None
                for b in reversed(content):
                    if isinstance(b, dict) and b.get("type") == "text":
                        raw = b.get("text", "")
                        cl = _clean_text_block(raw)
                        if cl:
                            last_text_block = cl
                            break
                if last_text_block:
                    user_msgs.append([("text", last_text_block)])
                # 如果最后一个 text 块清洗后为空（极端情况），则这条 user 消息视为空，不追加
            else:
                cl = _clean_text_block(str(content))
                if cl:
                    user_msgs.append([("text", cl)])
        elif role == "assistant":
            if isinstance(content, list):
                texts = []
                for b in content:
                    if isinstance(b, dict):
                        if b.get("type") == "text":
                            texts.append(("text", b.get("text", "")))
                        elif b.get("type") == "tool_use":
                            texts.append(("tool_use", f"调用工具 {b.get('name','')}"))
                        elif b.get("type") == "thinking":
                            texts.append(("thinking", b.get("thinking", "")[:100]))
                assistant_msgs.append(texts)
            elif isinstance(content, str):
                assistant_msgs.append([("text", content)])

    # 最新的用户消息（用于审批预览）——取清洗后的真实文本
    latest_user = ""
    for msg in reversed(msgs):
        if msg.get("role") == "user":
            c = msg.get("content", "")
            if isinstance(c, list):
                # 只取最后一个有效的 text 块（用户真正输入的那一段）
                for b in reversed(c):
                    if isinstance(b, dict) and b.get("type") == "text":
                        cl = _clean_text_block(b.get("text", ""))
                        if cl:
                            latest_user = cl[:500]
                            break
            else:
                latest_user = _clean_text_block(str(c))[:500]
            break

    return {
        "id": "",
        "model": model,
        "stream": stream,
        "system_prompt_len": system_prompt_len,
        "system_prompt_preview": system[:500] if system else "",
        "latest_user": latest_user[:500],
        "user_count": len(user_msgs),
        "assistant_count": len(assistant_msgs),
        "tool_result_count": len(tool_results),
        "has_tool_results": len(tool_results) > 0,
        "has_tool_calls": any(
            any(t[0] == "tool_use" for t in assistant)
            for assistant in assistant_msgs
        ),
        # 完整数据
        "system_prompt_full": system if system else "",
        "user_messages": user_msgs,
        "assistant_messages": assistant_msgs,
        "tool_results": tool_results,
    }


def get_pending_list() -> list[dict]:
    """获取待审批列表。"""
    now = time.time()
    result = []
    for req_id, item in list(_pending.items()):
        if item["status"] == "pending":
            data = item["data"]
            info = _extract_preview(data)
            info["id"] = req_id
            info["waiting"] = round(now - item["created_at"], 1)
            result.append(info)
    return result


def get_request_detail(req_id: str) -> dict | None:
    """获取单个请求的完整详情。"""
    item = _pending.get(req_id)
    if not item:
        return None
    info = _extract_preview(item["data"])
    info["id"] = req_id
    info["status"] = item["status"]
    info["waiting"] = round(time.time() - item["created_at"], 1)
    info["request_data"] = item["data"]
    info["request_data_display"], info["request_data_size"] = _make_display_json(item["data"])
    return info


def _make_display_json(data: dict) -> tuple[dict, int]:
    """把请求体转成"占位符版"用于前端展示。

    规则（仅最新一条 user 消息）：
    - 只保留 messages 中最后一条 role="user" 的消息
    - 所有其他消息（历史 user、system、assistant、tool 等）全部删除
    - 保留的最新 user 消息中的 <system-reminder> 块替换为"已省略"
    - 其他顶层字段（model, tools, temperature 等）保留

    Returns: (display_data, original_size_bytes)
    """
    out = copy.deepcopy(data)

    # 原始字节数
    try:
        original_size = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    except Exception:
        original_size = 0

    msgs = out.get("messages", [])
    if msgs:
        # 找到最后一条 user 消息
        last_user_idx = None
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].get("role") == "user":
                last_user_idx = i
                break

        if last_user_idx is not None:
            # 只保留这一条
            msg = msgs[last_user_idx]
            content = msg.get("content", "")

            # 清理 Claude Code 注入的各种 wrapper/metadata 块
            def _strip_claude_injections(text: str) -> str:
                if not isinstance(text, str):
                    return text
                # 移除已知的系统注入标签块（跨行）
                patterns = [
                    r"<system-reminder>.*?</system-reminder>",
                    r"<local-command-caveat>.*?</local-command-caveat>",
                    r"<command-name>.*?</command-name>",
                    r"<command-args>.*?</command-args>",
                    r"<local-command-stdout>.*?</local-command-stdout>",
                    # 兜底：移除其他看起来像 Claude Code 注入的 <tag>...</tag> 块
                    # （只匹配看起来是 metadata 的，保守起见只做已知列表 + 常见前缀）
                ]
                for pat in patterns:
                    text = re.sub(pat, "", text, flags=re.DOTALL)
                # 清理多余空行和首尾空白
                text = re.sub(r"\n{3,}", "\n\n", text).strip()
                return text

            # 对 user 消息做清理
            if isinstance(content, list):
                cleaned = []
                for b in content:
                    if isinstance(b, dict):
                        t = b.get("type", "")
                        if t == "text":
                            raw_text = b.get("text", "")
                            cleaned_text = _strip_claude_injections(raw_text)
                            if not cleaned_text or cleaned_text.strip() == "":
                                continue
                            cleaned.append({**b, "text": cleaned_text})
                        else:
                            # 其他类型（如 tool_result）按原样保留或也过滤，当前先保留
                            cleaned.append(b)
                    else:
                        cleaned.append(b)
                msg["content"] = cleaned
            elif isinstance(content, str):
                cleaned_str = _strip_claude_injections(content)
                msg["content"] = cleaned_str

            out["messages"] = [msg]
        else:
            out["messages"] = []

    # tools 字段过滤
    if "tools" in out:
        if isinstance(out["tools"], list):
            tool_count = len(out["tools"])
            out["tools"] = f"🔶 [已过滤，共 {tool_count} 个工具定义]"
        else:
            out["tools"] = "🔶 [已过滤]"

    return out, original_size


def extract_clean_user_prompt(data: dict) -> str:
    """从 Claude Code 原始请求 body 中提取最终要发给 DeepSeek 的干净 prompt。

    规则（与管理页面脱敏展示保持完全一致）：
    - 只保留 messages 中最后一条 role="user" 的消息
    - 在该消息的 content 列表中，只取最后一个 type="text" 的块（即用户真正输入的那一段）
    - 去除所有已知的 harness / Claude Code 注入标签块：
        <system-reminder>、<local-command-caveat>、<command-name>、
        <command-message>、<command-args>、<local-command-stdout> 等
    - 返回清洗后的纯字符串 prompt（若无可用的文本则返回空字符串）

    这个函数是执行路径（真正发给 DeepSeek）和预览路径共用的唯一来源，
    保证“管理员在网页上看到的内容”和“实际放行后发出去的内容”完全一致。
    """
    msgs = data.get("messages", []) or []

    # 定位最后一条 user 消息
    last_user_idx = None
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") == "user":
            last_user_idx = i
            break

    if last_user_idx is None:
        return ""

    content = msgs[last_user_idx].get("content", "")

    # 注入块清洗（与 _extract_preview 里的 _clean_text_block 逻辑完全相同）
    def _strip_injections(text: str) -> str:
        if not isinstance(text, str):
            return ""
        patterns = [
            r"<system-reminder>.*?</system-reminder>",
            r"<local-command-caveat>.*?</local-command-caveat>",
            r"<command-name>.*?</command-name>",
            r"<command-message>.*?</command-message>",
            r"<command-args>.*?</command-args>",
            r"<local-command-stdout>.*?</local-command-stdout>",
            # Claude Code 自动注入的"建议模式"提示块（自动发给 Claude 的指令，
            # 不应该转发给 DeepSeek —— 它是 Claude 的内部 housekeeping）
            r"\[SUGGESTION MODE:.*?\]",
            r"\[SUGGESTION-MODE:.*?\]",
            # Claude Code 自动注入的"写个标题"等任务指令
            # —— 只剥后面的 "Write the title..." 部分，
            # <session>...</session> 里包的是用户真话，要保留
            r"Write the title in the language.*?regardless of the language of the examples above\.\s*",
            r"Write the title.*?the examples above\.\s*",
        ]
        for pat in patterns:
            text = re.sub(pat, "", text, flags=re.DOTALL | re.IGNORECASE)
        # 清理多余空行，保留用户可能的换行意图
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    if isinstance(content, list):
        # 从后往前找最后一个有效的 text 块
        for b in reversed(content):
            if isinstance(b, dict) and b.get("type") == "text":
                raw = b.get("text", "")
                cleaned = _strip_injections(raw)
                if cleaned:
                    return cleaned
        return ""
    elif isinstance(content, str):
        return _strip_injections(content)
    else:
        return ""


def is_claude_housekeeping_request(data: dict) -> bool:
    """检测整个请求是不是 Claude Code 的「后台 housekeeping」（不应该发给 DeepSeek）。

    触发条件（任一）：
    - 最新 user 消息清洗后**完全是空的**（说明只是注入块、没有用户真实输入）
    - 最新 user 消息**只包含** SUGGESTION MODE 之类的 Claude 内部指令
    - **整个 body 里任一文本块包含** housekeeping 标记（即使被夹在 user 真消息里）
      （Claude Code 会把 SUGGESTION MODE 模板塞进 user 的 system-reminder 区，
      我们的清洗已经剥掉了这块，但如果它还出现在 user 文本里 → 整个请求是 housekeeping）
    - body 顶层带 `metadata.claude_code_housekeeping` 之类的标记（预留）

    返回 True = 应该丢弃请求，不发给 DeepSeek
    """
    prompt = extract_clean_user_prompt(data)
    if not prompt:
        # 没提取出任何用户真实文本 → 整个请求是 Claude Code 自己的后台调用
        return True

    # 1) 兜底：清洗后 prompt 只是固定 housekeeping 文案
    housekeeping_keywords = [
        "suggest what the user might naturally type",
        "look at the user's recent messages",
        "stay silent if the next step isn't obvious",
        "format: 2-12 words",
        "reply with only the suggestion",
        "your job is to predict",
        "first: look at the user's recent messages",
        "the test: would they think",
        # Claude Code 自动注入的"标题生成"指令（偷偷发的 housekeeping）
        "write the title in the language",
        "regardless of the language of the examples above",
    ]
    pl = prompt.lower()
    if any(kw in pl for kw in housekeeping_keywords):
        return True

    # 2) 扫描整个 body 所有文本块（包括 system / 注入块），含 housekeeping 标记就丢弃
    housekeeping_markers = [
        "[suggestion mode",
        "suggestion mode:",
        "predict what they would type",
        "stay silent if the next step isn't obvious",
        # 标题生成 / 摘要生成 等 Claude Code 自动 housekeeping
        "write the title in the language",
        "write a title for",
        "regardless of the language of the examples above",
    ]
    body_text = json.dumps(data, ensure_ascii=False).lower() if data else ""
    if any(m in body_text for m in housekeeping_markers):
        return True

    return False


def approve(req_id: str) -> bool:
    """放行请求。"""
    item = _pending.get(req_id)
    if not item or item["status"] != "pending":
        return False
    item["status"] = "approved"
    item["event"].set()
    print(f"[审批] {req_id} 已放行")
    return True


def reject(req_id: str) -> bool:
    """拒绝请求。"""
    item = _pending.get(req_id)
    if not item or item["status"] != "pending":
        return False
    item["status"] = "rejected"
    item["error"] = "请求已被管理员拒绝"
    item["event"].set()
    print(f"[审批] {req_id} 已拒绝")
    return True


def wait_for_result(req_id: str, event: asyncio.Event) -> Any:
    """等待审批结果。"""
    item = _pending.get(req_id)
    if not item:
        return None, "请求已过期"
    return item["result"], item["error"]


def set_result(req_id: str, result: Any) -> None:
    """设置请求结果（审批通过后由执行器调用）。"""
    item = _pending.get(req_id)
    if item:
        item["result"] = result
        item["status"] = "completed"


def cleanup_old(ttl: int = 300) -> None:
    """清理超过 TTL 的已处理请求。"""
    now = time.time()
    for req_id, item in list(_pending.items()):
        if item["status"] != "pending" and now - item["created_at"] > ttl:
            del _pending[req_id]
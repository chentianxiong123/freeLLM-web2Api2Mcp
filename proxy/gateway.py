"""请求过滤 — housekeeping 检测 + prompt 提取

Claude Code 的 housekeeping 请求（标题生成、建议模式等）直接丢弃，不发给 DeepSeek。
"""

import json
import re


def extract_clean_user_prompt(data: dict) -> str:
    """从 Claude Code 原始请求 body 中提取最终要发给 DeepSeek 的干净 prompt。

    规则：
    - 只保留 messages 中最后一条 role="user" 的消息
    - 在该消息的 content 列表中，只取最后一个 type="text" 的块
    - 去除所有已知的 harness / Claude Code 注入标签块
    - 返回清洗后的纯字符串 prompt
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

    # 注入块清洗
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
            r"\[SUGGESTION MODE:.*?\]",
            r"\[SUGGESTION-MODE:.*?\]",
            r"Write the title in the language.*?regardless of the language of the examples above\.\s*",
            r"Write the title.*?the examples above\.\s*",
        ]
        for pat in patterns:
            text = re.sub(pat, "", text, flags=re.DOTALL | re.IGNORECASE)
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

    返回 True = 应该丢弃请求，不发给 DeepSeek
    """
    # 直接扫原始 body JSON（不 strip），命中即丢
    body_text = json.dumps(data, ensure_ascii=False).lower() if data else ""

    # 标题生成：system message 里有 "generate a concise" + user message 里有 "write the title"
    if "generate a concise" in body_text and "title" in body_text:
        return True

    # suggestion 模式
    suggestion_markers = [
        "[suggestion mode",
        "suggestion mode:",
        "predict what they would type",
        "stay silent if the next step isn't obvious",
        "your job is to predict",
        "first: look at the user's recent messages",
        "the test: would they think",
        "format: 2-12 words",
        "reply with only the suggestion",
    ]
    if any(m in body_text for m in suggestion_markers):
        return True

    # 标题指令（fallback）
    title_markers = [
        "write the title in the language",
        "write a title for",
        "regardless of the language of the examples above",
    ]
    if any(m in body_text for m in title_markers):
        return True

    return False

"""OpenAI body → 上游 ChatRequest 转换。

从 CC 等下游的 OpenAI 格式消息中提取要发给上游（DeepSeek 等）的内容。
"""

import json
from dataclasses import dataclass


@dataclass
class ChatRequest:
    """描述一次"发到 Provider 的请求"。"""
    user_content: str
    is_react_continuation: bool
    tool_call_ids: list[str]


def build_ds_input(body: dict) -> ChatRequest:
    """从 OpenAI 风格 body 构造 ChatRequest。

    判定规则（只看末尾，不看历史）：
      - 最后一条 role=tool → react 续接 → 发这条 tool 的内容
      - 最后一条 role=user → 新的人话 → 发这条 user 的内容
    """
    msgs = body.get("messages", []) or []
    last = msgs[-1] if msgs else {}
    last_role = last.get("role", "?")

    print(f"[build_ds_input] msgs count={len(msgs)}, last_role={last_role}")

    if last_role == "tool":
        tcid = last.get("tool_call_id", "")
        c = last.get("content", "")
        if isinstance(c, str):
            content = c
        elif isinstance(c, list):
            parts = []
            for b in c:
                if isinstance(b, dict):
                    if b.get("type") == "text":
                        parts.append(b.get("text", ""))
                    else:
                        parts.append(json.dumps(b, ensure_ascii=False))
            content = "\n".join(parts)
        else:
            content = str(c)
        print(f"[build_ds_input] → REACT continuation, tool_call_id={tcid}")
        return ChatRequest(user_content=content, is_react_continuation=True, tool_call_ids=[tcid])

    if last_role == "user":
        c = last.get("content", "")
        if isinstance(c, str):
            content = c
        elif isinstance(c, list):
            parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
            content = "\n".join(parts)
        else:
            content = str(c)
        print(f"[build_ds_input] → USER message, len={len(content)}")
        return ChatRequest(user_content=content, is_react_continuation=False, tool_call_ids=[])

    for m in reversed(msgs):
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, str):
                content = c
            elif isinstance(c, list):
                parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
                content = "\n".join(parts)
            else:
                content = str(c)
            print(f"[build_ds_input] → FALLBACK to last user, len={len(content)}")
            return ChatRequest(user_content=content, is_react_continuation=False, tool_call_ids=[])
    return ChatRequest(user_content="", is_react_continuation=False, tool_call_ids=[])

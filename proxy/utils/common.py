"""公共工具函数。"""

from __future__ import annotations

import json
import os
from typing import Any


def extract_text_content(message: dict) -> str:
    """从 OpenAI message 中提取纯文本。

    处理三种格式：
    - str: 直接返回
    - list[{type: "text"}]: 拼接所有 text 块
    - 其他: str() 兜底
    """
    c = message.get("content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [
            b.get("text", "")
            for b in c
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(parts)
    return str(c)


def next_id(items: list[dict], prefix: str, key: str = "id") -> str:
    """生成下一个 ID（acc_001, r001 等）。"""
    existing = []
    for item in items:
        rid = item.get(key, "")
        if rid.startswith(prefix):
            try:
                existing.append(int(rid[len(prefix):]))
            except ValueError:
                pass
    num = (max(existing) + 1) if existing else 1
    return f"{prefix}{num:03d}"


def sanitize_headers(headers: dict) -> dict:
    """脱敏 HTTP headers（截断敏感字段）。"""
    safe = {}
    for k, v in headers.items():
        sv = str(v)
        if k.lower() in ("authorization", "cookie", "x-ds-pow-response"):
            safe[k] = sv[:20] + "..." if len(sv) > 20 else sv
        else:
            safe[k] = sv[:200]
    return safe


def truncate_body(body: Any, max_len: int = 10000) -> Any:
    """截断请求/响应 body（避免日志过大）。"""
    if body is None:
        return None
    if isinstance(body, (str, int, float, bool)):
        return body
    try:
        text = json.dumps(body, ensure_ascii=False, default=str)
        if len(text) > max_len:
            return text[:max_len] + "...(truncated)"
    except Exception:
        pass
    return body


def expand_tilde(args: dict) -> dict:
    """把参数值里的 ~/X 展开成绝对路径。"""
    if not isinstance(args, dict):
        return args
    home = None
    for v in args.values():
        if isinstance(v, str) and ("~/" in v or v.startswith("~")):
            if home is None:
                home = os.path.expanduser("~")
            break
    if home is None:
        return args
    out = {}
    for k, v in args.items():
        if isinstance(v, str):
            if v == "~":
                out[k] = home
            elif v.startswith("~/"):
                out[k] = home + v[1:]
            else:
                out[k] = v
        else:
            out[k] = v
    return out

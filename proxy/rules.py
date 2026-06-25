"""Simple rule engine for blocking requests.

Storage: proxy/rules.json
Rule structure:
{
    "id": "r001",
    "name": "SUGGESTION MODE",
    "match_type": "substring",   # "substring" | "regex"
    "scope": "request",          # "request" | "response"
    "pattern": "suggestion mode",
    "action": "block",           # "block" | "strip"
    "enabled": true,
    "note": "Description...",
    "created_at": 1781543900,
    "updated_at": 1781543900
}

作用域：
  - request: 拦截用户请求，不发给 DS
  - response: 过滤 DS 返回的内容

匹配方式：
  - substring: pattern in text（大小写不敏感）
  - regex: re.search(pattern, text)（大小写不敏感）

响应过滤动作：
  - block: 整个响应返回空
  - strip: 只删除匹配的内容，其他保留
"""

import re
import time
from pathlib import Path

from utils.json_store import JsonStore
from utils.common import next_id

_store = JsonStore(
    path=Path(__file__).parent / "rules.json",
    default_factory=lambda: {"version": 1, "rules": []},
)


def _load() -> dict:
    return _store.load()


def _save(data: dict) -> None:
    _store.save(data)


# -- CRUD --


def list_rules() -> list[dict]:
    data = _load()
    return sorted(data.get("rules", []), key=lambda r: r.get("id", ""))


def get_rule(rule_id: str) -> dict | None:
    for r in list_rules():
        if r.get("id") == rule_id:
            return r
    return None


def add_rule(rule: dict) -> dict:
    data = _load()
    rules = data.setdefault("rules", [])

    new_id = next_id(rules, "r")

    match_type = rule.get("match_type", "substring")
    if match_type not in ("substring", "regex"):
        match_type = "substring"
    scope = rule.get("scope", "request")
    if scope not in ("request", "response"):
        scope = "request"
    action = rule.get("action", "block")
    if action not in ("block", "strip", "intercept"):
        action = "block"

    now = int(time.time())
    new_rule = {
        "id": new_id,
        "name": rule.get("name", "").strip() or "未命名规则",
        "match_type": match_type,
        "scope": scope,
        "action": action,
        "pattern": rule.get("pattern", ""),
        "enabled": bool(rule.get("enabled", True)),
        "note": rule.get("note", ""),
        "created_at": now,
        "updated_at": now,
    }
    rules.append(new_rule)
    _save(data)
    return new_rule


def update_rule(rule_id: str, patch: dict) -> dict | None:
    data = _load()
    rules = data.setdefault("rules", [])
    valid_match_types = ("substring", "regex")
    valid_scopes = ("request", "response")
    valid_actions = ("block", "strip", "intercept")
    for r in rules:
        if r.get("id") == rule_id:
            for k in ("name", "match_type", "scope", "action", "pattern", "enabled", "note"):
                if k in patch:
                    if k == "match_type" and patch[k] in valid_match_types:
                        r[k] = patch[k]
                    elif k == "scope" and patch[k] in valid_scopes:
                        r[k] = patch[k]
                    elif k == "action" and patch[k] in valid_actions:
                        r[k] = patch[k]
                    else:
                        r[k] = patch[k]
            r["updated_at"] = int(time.time())
            _save(data)
            return r
    return None


def delete_rule(rule_id: str) -> bool:
    data = _load()
    rules = data.setdefault("rules", [])
    new_rules = [r for r in rules if r.get("id") != rule_id]
    if len(new_rules) == len(rules):
        return False
    data["rules"] = new_rules
    _save(data)
    return True


def toggle_rule(rule_id: str, enabled: bool | None = None) -> dict | None:
    data = _load()
    rules = data.setdefault("rules", [])
    for r in rules:
        if r.get("id") == rule_id:
            r["enabled"] = (not r.get("enabled", True)) if enabled is None else bool(enabled)
            r["updated_at"] = int(time.time())
            _save(data)
            return r
    return None


DEFAULT_RULES = [
    {
        "id": "r001",
        "name": "SUGGESTION MODE",
        "match_type": "substring",
        "scope": "request",
        "action": "block",
        "pattern": "suggestion mode",
        "enabled": True,
        "note": "拦截 Claude Code 的 SUGGESTION MODE 提示",
        "created_at": 0,
        "updated_at": 0,
    },
    {
        "id": "r002",
        "name": "SYSTEM REMINDER",
        "match_type": "regex",
        "scope": "request",
        "action": "strip",
        "pattern": r"<system-reminder>.*?</system-reminder>",
        "enabled": True,
        "note": "从请求中剥离 CC 注入的 system-reminder 标签",
        "created_at": 0,
        "updated_at": 0,
    },
    {
        "id": "r003",
        "name": "COMPACT",
        "match_type": "substring",
        "scope": "request",
        "action": "intercept",
        "pattern": "Your task is to create a detailed summary of the conversation so far",
        "enabled": True,
        "note": "检测 Claude Code 的 /compact 压缩请求，触发上游会话重置",
        "created_at": 0,
        "updated_at": 0,
    },
]


def reset_to_defaults() -> list[dict]:
    """重置为默认规则集。"""
    now = int(time.time())
    data = {
        "version": 1,
        "rules": [
            {**r, "created_at": now, "updated_at": now}
            for r in DEFAULT_RULES
        ],
    }
    _save(data)
    return data["rules"]


# -- Matching --


def _extract_user_text(body: dict) -> str:
    msgs = body.get("messages", []) or []
    chunks = []
    for m in msgs:
        if m.get("role") != "user":
            continue
        c = m.get("content", "")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    chunks.append(b.get("text", ""))
        elif isinstance(c, str):
            chunks.append(c)
    return "\n".join(chunks)


def is_blocked(body: dict, clean_prompt: str) -> tuple[bool, dict | None]:
    """检查请求是否被拦截（只匹配 scope=request 的 block 规则）。"""
    text = _extract_user_text(body) + "\n" + clean_prompt
    if not text:
        return False, None

    for r in list_rules():
        if not r.get("enabled", True):
            continue
        if r.get("scope", "request") != "request":
            continue
        if r.get("action", "block") != "block":
            continue
        pattern = r.get("pattern", "").strip()
        if not pattern:
            continue
        match_type = r.get("match_type", "substring")

        try:
            if match_type == "regex":
                if re.search(pattern, text, re.DOTALL | re.IGNORECASE):
                    return True, r
            else:
                if pattern.lower() in text.lower():
                    return True, r
        except re.error:
            continue

    return False, None


def find_intercept_rule(body: dict) -> dict | None:
    """查找匹配的 intercept 规则（scope=request, action=intercept）。

    用于检测 /compact 等需要特殊处理的请求。
    返回匹配的规则 dict，无匹配返回 None。
    """
    text = _extract_user_text(body)
    if not text:
        return None

    for r in list_rules():
        if not r.get("enabled", True):
            continue
        if r.get("scope", "request") != "request":
            continue
        if r.get("action") != "intercept":
            continue
        pattern = r.get("pattern", "").strip()
        if not pattern:
            continue
        match_type = r.get("match_type", "substring")

        try:
            if match_type == "regex":
                if re.search(pattern, text, re.DOTALL | re.IGNORECASE):
                    return r
            else:
                if pattern.lower() in text.lower():
                    return r
        except re.error:
            continue

    return None


def clean_request_content(content: str) -> tuple[str, list[dict]]:
    """剥离请求内容中的匹配段（只匹配 scope=request, action=strip 的规则）。

    不做拦截，只剥离匹配内容。用于清理 CC 注入的标签。
    Returns: (剥离后的内容, 命中的规则列表)
    """
    if not content:
        return content, []

    hits = []
    for r in list_rules():
        if not r.get("enabled", True):
            continue
        if r.get("scope", "request") != "request":
            continue
        if r.get("action") != "strip":
            continue
        pattern = r.get("pattern", "").strip()
        if not pattern:
            continue
        match_type = r.get("match_type", "substring")

        try:
            if match_type == "regex":
                if not re.search(pattern, content, re.DOTALL | re.IGNORECASE):
                    continue
                content = re.sub(pattern, "", content, flags=re.DOTALL | re.IGNORECASE)
            else:
                idx = content.lower().find(pattern.lower())
                if idx < 0:
                    continue
                content = content[:idx] + content[idx + len(pattern):]
        except re.error:
            continue

        hits.append(r)

    return content.strip(), hits


def filter_response(content: str) -> tuple[str, list[dict]]:
    """过滤 DS 返回的内容（只匹配 scope=response 的规则）。

    action=block: 整个响应返回空
    action=strip: 只删除匹配内容

    Returns: (过滤后的内容, 命中的规则列表)
    """
    if not content:
        return content, []

    hits = []
    for r in list_rules():
        if not r.get("enabled", True):
            continue
        if r.get("scope") != "response":
            continue
        pattern = r.get("pattern", "").strip()
        if not pattern:
            continue
        match_type = r.get("match_type", "substring")
        action = r.get("action", "block")

        try:
            if match_type == "regex":
                if not re.search(pattern, content, re.DOTALL | re.IGNORECASE):
                    continue
            else:
                if pattern.lower() not in content.lower():
                    continue
        except re.error:
            continue

        hits.append(r)

        if action == "block":
            return "", hits
        elif action == "strip":
            try:
                if match_type == "regex":
                    content = re.sub(pattern, "", content, flags=re.DOTALL | re.IGNORECASE)
                else:
                    # substring strip: 大小写不敏感替换
                    idx = content.lower().find(pattern.lower())
                    if idx >= 0:
                        content = content[:idx] + content[idx + len(pattern):]
            except re.error:
                pass

    return content.strip(), hits

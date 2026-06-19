"""Simple rule engine for blocking requests.

Storage: proxy/rules.json
Rule structure:
{
    "id": "r001",
    "name": "SUGGESTION MODE",
    "pattern": "suggestion mode",
    "enabled": true,
    "note": "Description...",
    "created_at": 1781543900,
    "updated_at": 1781543900
}

Matching: simple substring match on user message text (case-insensitive).
If any enabled rule's pattern is found, the request is blocked.
"""

import json
import time
import threading
from pathlib import Path

_FILE = Path(__file__).parent / "rules.json"
_LOCK = threading.Lock()


def _load() -> dict:
    with _LOCK:
        if not _FILE.exists():
            return {"version": 1, "rules": []}
        try:
            return json.loads(_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"version": 1, "rules": []}


def _save(data: dict) -> None:
    with _LOCK:
        _FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


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

    existing_nums = []
    for r in rules:
        rid = r.get("id", "")
        if rid.startswith("r"):
            try:
                existing_nums.append(int(rid[1:]))
            except ValueError:
                pass
    next_num = (max(existing_nums) + 1) if existing_nums else 1
    new_id = f"r{next_num:03d}"

    now = int(time.time())
    new_rule = {
        "id": new_id,
        "name": rule.get("name", "").strip() or "未命名规则",
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
    for r in rules:
        if r.get("id") == rule_id:
            for k in ("name", "pattern", "enabled", "note"):
                if k in patch:
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
        "pattern": "suggestion mode",
        "enabled": True,
        "note": "拦截 Claude Code 的 SUGGESTION MODE 提示",
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
    text = _extract_user_text(body)
    if not text:
        return False, None

    text_lower = text.lower()
    for r in list_rules():
        if not r.get("enabled", True):
            continue
        pattern = r.get("pattern", "").strip()
        if not pattern:
            continue
        if pattern.lower() in text_lower:
            return True, r

    return False, None

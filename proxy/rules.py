"""违规请求拦截规则引擎

存储：proxy/rules.json
{
    "version": 1,
    "rules": [
        {
            "id": "r001",
            "name": "SUGGESTION MODE",
            "type": "keyword_substring" | "regex" | "empty_clean_prompt",
            "pattern": "suggestion mode",      # 关键词/正则；empty_clean_prompt 不需要 pattern
            "scope": "body" | "clean_prompt" | "user_text_blocks",
            "case_sensitive": false,
            "enabled": true,
            "note": "Claude Code 后台指令...",
            "created_at": 1781543900,
            "updated_at": 1781543900,
        },
        ...
    ]
}

匹配流程（is_blocked）：
- 顺序遍历所有 enabled 的规则
- 任一命中 → 返回 (True, rule)
- 都不命中 → 返回 (False, None)
"""

import json
import re
import time
import threading
from pathlib import Path

_FILE = Path(__file__).parent / "rules.json"
_LOCK = threading.Lock()

# ── 默认规则集（首次启动写入文件）─────────────────────────

DEFAULT_RULES = [
    {
        "id": "r001",
        "name": "清洗后空 prompt",
        "type": "empty_clean_prompt",
        "scope": "any",
        "enabled": True,
        "note": "整条 user 消息剥掉所有注入块后为空 → 整条请求是 Claude Code 后台 housekeeping",
    },
    {
        "id": "r002",
        "name": "SUGGESTION MODE",
        "type": "keyword_substring",
        "pattern": "suggestion mode",
        "scope": "body",
        "case_sensitive": False,
        "enabled": True,
        "note": "Claude Code 后台让模型预测用户下一句——绝不应该发给 DeepSeek",
    },
    {
        "id": "r003",
        "name": "predict what they would type",
        "type": "keyword_substring",
        "pattern": "predict what they would type",
        "scope": "body",
        "case_sensitive": False,
        "enabled": True,
        "note": "SUGGESTION MODE 内置模板",
    },
    {
        "id": "r004",
        "name": "stay silent if next step not obvious",
        "type": "keyword_substring",
        "pattern": "stay silent if the next step isn't obvious",
        "scope": "body",
        "case_sensitive": False,
        "enabled": True,
        "note": "SUGGESTION MODE 内置模板",
    },
    {
        "id": "r005",
        "name": "suggest what user might naturally type",
        "type": "keyword_substring",
        "pattern": "suggest what the user might naturally type",
        "scope": "body",
        "case_sensitive": False,
        "enabled": True,
        "note": "SUGGESTION MODE 内置模板",
    },
    {
        "id": "r006",
        "name": "your job is to predict",
        "type": "keyword_substring",
        "pattern": "your job is to predict",
        "scope": "body",
        "case_sensitive": False,
        "enabled": True,
        "note": "Claude 后台指令",
    },
    {
        "id": "r007",
        "name": "format: 2-12 words",
        "type": "keyword_substring",
        "pattern": "format: 2-12 words",
        "scope": "body",
        "case_sensitive": False,
        "enabled": True,
        "note": "SUGGESTION MODE 输出格式要求",
    },
    {
        "id": "r008",
        "name": "reply with only the suggestion",
        "type": "keyword_substring",
        "pattern": "reply with only the suggestion",
        "scope": "body",
        "case_sensitive": False,
        "enabled": True,
        "note": "SUGGESTION MODE 输出格式要求",
    },
    {
        "id": "r009",
        "name": "first: look at user's recent messages",
        "type": "keyword_substring",
        "pattern": "first: look at the user's recent messages",
        "scope": "body",
        "case_sensitive": False,
        "enabled": True,
        "note": "SUGGESTION MODE 内置模板",
    },
    {
        "id": "r010",
        "name": "the test: would they think",
        "type": "keyword_substring",
        "pattern": "the test: would they think",
        "scope": "body",
        "case_sensitive": False,
        "enabled": True,
        "note": "SUGGESTION MODE 内置模板",
    },
    {
        "id": "r011",
        "name": "look at user's recent messages",
        "type": "keyword_substring",
        "pattern": "look at the user's recent messages",
        "scope": "body",
        "case_sensitive": False,
        "enabled": True,
        "note": "SUGGESTION MODE 内置模板",
    },
]


def _default_data() -> dict:
    """首次启动：写默认规则到文件。"""
    now = int(time.time())
    rules = []
    for r in DEFAULT_RULES:
        rules.append({
            **r,
            "created_at": now,
            "updated_at": now,
        })
    return {"version": 1, "rules": rules}


def _load() -> dict:
    """读 rules.json，不存在则写默认。"""
    with _LOCK:
        if not _FILE.exists():
            data = _default_data()
            _FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return data
        try:
            return json.loads(_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return _default_data()


def _save(data: dict) -> None:
    with _LOCK:
        _FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ── 公开 API ──────────────────────────────────────────


def list_rules() -> list[dict]:
    """列出所有规则（按 id 排序）。"""
    data = _load()
    return sorted(data.get("rules", []), key=lambda r: r.get("id", ""))


def get_rule(rule_id: str) -> dict | None:
    """按 id 查单条规则。"""
    for r in list_rules():
        if r.get("id") == rule_id:
            return r
    return None


def add_rule(rule: dict) -> dict:
    """新增一条规则。自动生成 id。

    必填：name, type
    选填：pattern (keyword_substring / regex 必填), scope, case_sensitive, enabled, note
    """
    data = _load()
    rules = data.setdefault("rules", [])

    # 生成 id：rNNN 找下一个可用号
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
        "type": rule.get("type", "keyword_substring"),
        "pattern": rule.get("pattern", ""),
        "scope": rule.get("scope", "body"),
        "case_sensitive": bool(rule.get("case_sensitive", False)),
        "enabled": bool(rule.get("enabled", True)),
        "note": rule.get("note", ""),
        "created_at": now,
        "updated_at": now,
    }
    rules.append(new_rule)
    _save(data)
    return new_rule


def update_rule(rule_id: str, patch: dict) -> dict | None:
    """更新规则（部分字段）。"""
    data = _load()
    rules = data.setdefault("rules", [])
    target = None
    for r in rules:
        if r.get("id") == rule_id:
            target = r
            break
    if not target:
        return None
    for k in ("name", "pattern", "scope", "case_sensitive", "enabled", "note", "type"):
        if k in patch:
            target[k] = patch[k]
    target["updated_at"] = int(time.time())
    _save(data)
    return target


def delete_rule(rule_id: str) -> bool:
    """删除规则。"""
    data = _load()
    rules = data.setdefault("rules", [])
    new_rules = [r for r in rules if r.get("id") != rule_id]
    if len(new_rules) == len(rules):
        return False
    data["rules"] = new_rules
    _save(data)
    return True


def toggle_rule(rule_id: str, enabled: bool | None = None) -> dict | None:
    """切换 enabled。enabled=None 则反转，否则设为指定值。"""
    data = _load()
    rules = data.setdefault("rules", [])
    target = None
    for r in rules:
        if r.get("id") == rule_id:
            target = r
            break
    if not target:
        return None
    target["enabled"] = (not target.get("enabled", True)) if enabled is None else bool(enabled)
    target["updated_at"] = int(time.time())
    _save(data)
    return target


def reset_to_defaults() -> list[dict]:
    """重置为默认规则集（先清空再写默认）。"""
    data = _default_data()
    _save(data)
    return data["rules"]


# ── 匹配引擎 ──────────────────────────────────────────


def _get_scope_text(scope: str, body: dict, clean_prompt: str, user_texts: str, full_body_text: str) -> str:
    """根据 scope 返回要匹配的文本。"""
    if scope == "clean_prompt":
        return clean_prompt
    if scope == "user_text_blocks":
        return user_texts
    if scope == "body":
        return full_body_text
    return full_body_text  # 默认 body


def _collect_user_text_blocks(body: dict) -> str:
    """把所有 user 消息的 text 块拼起来。"""
    import json as _json
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


def is_blocked(
    body: dict,
    clean_prompt: str,
) -> tuple[bool, dict | None]:
    """判断请求是否应被拦截。

    顺序遍历所有 enabled 规则，任一命中即拦截。
    返回 (True, rule) 或 (False, None)。
    """
    import json as _json

    full_body_text = _json.dumps(body, ensure_ascii=False, default=str) if body else ""
    user_texts = _collect_user_text_blocks(body)
    clean_prompt = clean_prompt or ""

    rules = list_rules()
    for r in rules:
        if not r.get("enabled", True):
            continue

        rtype = r.get("type", "")
        scope = r.get("scope", "body")
        text = _get_scope_text(scope, body, clean_prompt, user_texts, full_body_text)

        if rtype == "empty_clean_prompt":
            # 整条清洗后为空
            if scope == "any" or scope == "clean_prompt":
                if not clean_prompt.strip():
                    return True, r
            continue

        pattern = r.get("pattern", "")
        if not pattern:
            continue

        haystack = text if r.get("case_sensitive", False) else text.lower()
        needle = pattern if r.get("case_sensitive", False) else pattern.lower()

        if rtype == "keyword_substring":
            if needle in haystack:
                return True, r

        elif rtype == "regex":
            flags = 0 if r.get("case_sensitive", False) else re.IGNORECASE
            try:
                if re.search(pattern, text, flags):
                    return True, r
            except re.error:
                # 正则非法，忽略
                pass

    return False, None

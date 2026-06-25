"""会话管理

持久化到 sessions.json，结构：
{
    "active_session_id": "xxx",      # 当前活跃 session（与 config.json 同步）
    "sessions": {
        "xxx": {                       # 每个 session 的状态
            "label": "...",
            "last_message_id": "10",   # DeepSeek 端续接用
            "message_count": 5,        # 已经发了几条
            "created_at": 1781543900,
            "last_used_at": 1781543950,
        },
        ...
    }
}

兼容旧结构：单字段 "session": {...} → 自动迁移到新结构。
"""

import time
from pathlib import Path

import config
from utils.json_store import JsonStore

# Token 估算：不分语言，统一 char/2（中英文混合的经验值）
TOKEN_EST_RATIO = 2.0  # 每个 token 平均 2 字符


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数。DS 不返回精确值，按字符数估算。"""
    if not text:
        return 0
    return max(1, int(len(text) / TOKEN_EST_RATIO))


def _migrate_session(raw: dict) -> dict:
    """兼容老结构：{"session": {...}} → {"active_session_id": ..., "sessions": {...}}。"""
    if "sessions" not in raw:
        old = raw.get("session", {})
        sid = old.get("session_id", "")
        sessions = {}
        if sid:
            sessions[sid] = {
                "label": old.get("model", "default"),
                "last_message_id": old.get("last_message_id"),
                "message_count": 0,
                "created_at": old.get("created", time.time()),
                "last_used_at": old.get("last_used", time.time()),
                "account_id": "",  # 旧数据没有 account_id
            }
        return {
            "active_session_id": sid,
            "sessions": sessions,
        }
    raw.setdefault("active_session_id", "")
    raw.setdefault("sessions", {})
    # 为旧 session 添加 account_id 字段
    for sid, s in raw.get("sessions", {}).items():
        s.setdefault("account_id", "")
    return raw


_store = JsonStore(
    path=Path(__file__).parent / "sessions.json",
    default_factory=lambda: {"active_session_id": "", "sessions": {}},
    migrate=_migrate_session,
)


def _load() -> dict:
    """加载 sessions.json。"""
    return _store.load()


def _save(data: dict) -> None:
    """保存 sessions.json。"""
    _store.save(data)


# ── 旧 API 兼容（保留给其他模块用）─────────────────────────


def needs_renewal() -> bool:
    """不再自动判断续期，统一由用户手动切换 session。"""
    return False


def get_usage_status() -> dict:
    """返回当前 session 的累计 token 用量。"""
    db = _load()
    sid = db.get("active_session_id", "")
    s = db.get("sessions", {}).get(sid, {})
    inp = s.get("input_tokens", 0)
    out = s.get("output_tokens", 0)
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": inp + out,
        "message_count": s.get("message_count", 0),
    }


def on_new_session(session_id: str, model: str = "", account_id: str = "") -> None:
    """新建 session（注册到列表 + 设为 active + 同步 config.json）。

    注意：这只「注册」一个 session 入口。如果该 session_id 已存在则保留。
    """
    db = _load()
    now = time.time()
    sessions = db.setdefault("sessions", {})
    if session_id not in sessions:
        sessions[session_id] = {
            "label": model or "",
            "model": model or "deepseek-v4-flash",
            "last_message_id": None,
            "message_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "created_at": now,
            "last_used_at": now,
            "account_id": account_id,
        }
    else:
        # 更新 account_id（如果提供）
        if account_id:
            sessions[session_id]["account_id"] = account_id
    db["active_session_id"] = session_id
    _save(db)
    config.update_config(session_id=session_id, model=sessions[session_id].get("model", "deepseek-v4-flash"))


def set_last_message_id(message_id: str | int | None) -> None:
    """把 DeepSeek 端返回的 response_message_id 持久化下来（写到 active session）。"""
    db = _load()
    sid = db.get("active_session_id", "")
    if not sid:
        return
    s = db.setdefault("sessions", {}).setdefault(sid, {})
    # 存原值（int / None / str 兼容历史字符串数据）
    s["last_message_id"] = message_id
    s["last_used_at"] = time.time()
    db["sessions"][sid] = s
    _save(db)


def get_last_message_id() -> str | None:
    """获取当前 active session 的 last_message_id（用于续接）。"""
    db = _load()
    sid = db.get("active_session_id", "")
    return db.get("sessions", {}).get(sid, {}).get("last_message_id")


def clear_last_message_id() -> None:
    """重置 last_message_id（下次请求会创建新根消息）。"""
    set_last_message_id(None)


def add_tokens(prompt_tokens: int) -> None:
    """累加 prompt_tokens（目前 DeepSeek 端不返回 token 数，留接口备用）。"""
    if not prompt_tokens:
        return
    db = _load()
    sid = db.get("active_session_id", "")
    if not sid:
        return
    s = db.setdefault("sessions", {}).setdefault(sid, {})
    s["prompt_tokens"] = s.get("prompt_tokens", 0) + prompt_tokens
    s["last_used_at"] = time.time()
    db["sessions"][sid] = s
    _save(db)


def get_current_session_id() -> str:
    """获取当前活跃的 session_id（与 config.json 一致）。"""
    db = _load()
    return db.get("active_session_id", "")


# ── 新 API：多 session 管理 ──────────────────────────────


def list_sessions(account_id: str = "") -> list[dict]:
    """列出指定账号的 session（含 active 标记 + 累计 token 数），按 last_used_at 倒序。

    如果 account_id 为空，则返回所有 session（向后兼容）。
    """
    db = _load()
    sid_active = db.get("active_session_id", "")
    sessions = db.get("sessions", {})
    out = []
    for sid, s in sessions.items():
        # 如果指定了 account_id，只返回该账号的 session
        if account_id and s.get("account_id", "") != account_id:
            continue
        new_inp = s.get("new_input_tokens", 0)
        cached = s.get("cached_tokens", 0)
        out_t = s.get("output_tokens", 0)
        # 兼容旧字段
        old_inp = s.get("input_tokens", 0)
        if old_inp and not new_inp:
            new_inp = old_inp
        out.append({
            "session_id": sid,
            "active": sid == sid_active,
            "label": s.get("label", ""),
            "model": s.get("model", "deepseek-v4-flash"),
            "last_message_id": s.get("last_message_id"),
            "message_count": s.get("message_count", 0),
            "new_input_tokens": new_inp,
            "cached_tokens": cached,
            "output_tokens": out_t,
            "total_tokens": new_inp + cached + out_t,
            "created_at": s.get("created_at"),
            "last_used_at": s.get("last_used_at"),
            "account_id": s.get("account_id", ""),
        })
    out.sort(key=lambda x: x.get("last_used_at") or 0, reverse=True)
    return out


def activate_session(session_id: str) -> bool:
    """切换 active session（写 sessions.json + 同步 config.json + 同步 accounts.json）。

    返回 True/False 表示是否切换成功（session_id 存在就成功）。
    """
    db = _load()
    sessions = db.get("sessions", {})
    if session_id not in sessions:
        return False
    db["active_session_id"] = session_id
    sessions[session_id]["last_used_at"] = time.time()
    _save(db)
    config.update_config(session_id=session_id, model=sessions[session_id].get("model", "deepseek-v4-flash"))
    return True


def register_session(session_id: str, label: str = "", model: str = "", account_id: str = "") -> dict:
    """手动注册一个新 session（如果不存在则新建，存在则更新 label）。

    返回注册后的 session 详情。
    """
    db = _load()
    now = time.time()
    sessions = db.setdefault("sessions", {})
    if session_id in sessions:
        if label:
            sessions[session_id]["label"] = label
        if model:
            sessions[session_id]["model"] = model
        if account_id:
            sessions[session_id]["account_id"] = account_id
    else:
        sessions[session_id] = {
            "label": label or "",
            "model": model or "deepseek-v4-flash",
            "last_message_id": None,
            "message_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "created_at": now,
            "last_used_at": now,
            "account_id": account_id,
        }
    _save(db)
    return sessions[session_id]


def delete_session(session_id: str) -> tuple[bool, str | None]:
    """删除一个 session（不能删 active session）。

    返回 (成功, 错误信息)。
    """
    db = _load()
    if session_id not in db.get("sessions", {}):
        return False, "session 不存在"
    if session_id == db.get("active_session_id", ""):
        return False, "不能删除当前活跃 session（请先切换到别的 session）"
    db["sessions"].pop(session_id, None)
    _save(db)
    return True, None


def set_specific_last_message_id(session_id: str, message_id: str | int | None) -> bool:
    """给指定 session 设置 last_message_id（不限 active）。

    message_id=None → 清空续接点（下次会创建新根消息）。
    """
    db = _load()
    if session_id not in db.get("sessions", {}):
        return False
    db["sessions"][session_id]["last_message_id"] = message_id
    db["sessions"][session_id]["last_used_at"] = time.time()
    _save(db)
    return True


def get_active_model() -> str:
    """获取当前活跃 session 的模型。"""
    db = _load()
    sid = db.get("active_session_id", "")
    s = db.get("sessions", {}).get(sid, {})
    return s.get("model", "deepseek-v4-flash")


def increment_message_count(session_id: str | None = None) -> None:
    """某个 session 的消息数 +1（默认 active session）。"""
    db = _load()
    sid = session_id or db.get("active_session_id", "")
    if not sid:
        return
    s = db.setdefault("sessions", {}).setdefault(sid, {})
    s["message_count"] = s.get("message_count", 0) + 1
    s["last_used_at"] = time.time()
    db["sessions"][sid] = s
    _save(db)


def track_message(
    input_text: str,
    output_text: str = "",
    thinking_text: str = "",
    session_id: str | None = None,
) -> None:
    """记录一次消息交换的 token 用量。

    计算方式（估算降级）：
      - new_input_tokens: 本次新输入的 token（用户发的内容）
      - cached_tokens: 历史的输入+输出（之前的消息，被缓存了）
      - output_tokens: 本次输出 = 思考 + 回复

    思考不会被保存到历史，但计入本次输出。
    """
    db = _load()
    sid = session_id or db.get("active_session_id", "")
    if not sid:
        return
    s = db.setdefault("sessions", {}).setdefault(sid, {})

    # 本次新输入
    new_input = _estimate_tokens(input_text)
    # 本次输出 = 思考 + 回复
    thinking_tok = _estimate_tokens(thinking_text)
    output_tok = _estimate_tokens(output_text)
    total_output = thinking_tok + output_tok

    # cached_tokens = 之前累计的输入+输出（历史部分）
    # 必须在累加 new_input_tokens 和 output_tokens 之前计算
    prev_input = s.get("new_input_tokens", 0)
    prev_output = s.get("output_tokens", 0)
    s["cached_tokens"] = s.get("cached_tokens", 0) + prev_input + prev_output

    # 累加
    s["message_count"] = s.get("message_count", 0) + 1
    s["new_input_tokens"] = prev_input + new_input
    s["output_tokens"] = prev_output + total_output
    s["last_used_at"] = time.time()
    db["sessions"][sid] = s
    _save(db)

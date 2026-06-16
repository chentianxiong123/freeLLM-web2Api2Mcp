"""单会话跟踪（适配自 deepseek-free-api/session_store.py）

与原始版本的区别：
- 移除多账号前缀（ds_{account_id}）
- 移除 old_sessions 归档（不自动开新会话）
- 持久化到 config.json，不走独立 sessions.json
"""

import json
import time
from pathlib import Path

import config

# DeepSeek V4 上下文窗口 1M，留 10% 余量
TOKEN_THRESHOLD = 900_000

SESSION_FILE = Path(__file__).parent / "sessions.json"


def _load() -> dict:
    if not SESSION_FILE.exists():
        return {}
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    SESSION_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def needs_renewal() -> bool:
    """检查当前 session 是否需要续期（token 超限）。"""
    db = _load()
    s = db.get("session", {})
    return s.get("prompt_tokens", 0) > TOKEN_THRESHOLD


def get_usage_status() -> dict:
    """返回当前 session 的用量状态。"""
    db = _load()
    s = db.get("session", {})
    return {
        "prompt_tokens": s.get("prompt_tokens", 0),
        "threshold": TOKEN_THRESHOLD,
        "remaining": max(0, TOKEN_THRESHOLD - s.get("prompt_tokens", 0)),
    }


def on_new_session(session_id: str, model: str = "") -> None:
    """新建 session 时重置 token 计数 + 清空 last_message_id（新会话没有上一轮）。"""
    db = _load()
    now = time.time()
    db["session"] = {
        "session_id": session_id,
        "prompt_tokens": 0,
        "model": model,
        "created": now,
        "last_used": now,
        "last_message_id": None,  # 新会话从根消息开始
    }
    _save(db)
    # 同步更新 config.json 里的 session_id
    config.update_config(session_id=session_id)


def set_last_message_id(message_id: str | int | None) -> None:
    """把 DeepSeek 端返回的 response_message_id 持久化下来。

    下次发请求时，chat_completion 会读这个值当 parent_message_id 续接对话。
    这是防止「每次请求都创建新根消息、刷爆账号」的关键。
    """
    db = _load()
    s = db.get("session", {})
    s["last_message_id"] = str(message_id) if message_id is not None else None
    s["last_used"] = time.time()
    db["session"] = s
    _save(db)


def get_last_message_id() -> str | None:
    """获取当前 session 上一次的 response_message_id（用于续接）。"""
    db = _load()
    return db.get("session", {}).get("last_message_id")


def clear_last_message_id() -> None:
    """重置 last_message_id（下次请求会创建新根消息）。"""
    db = _load()
    s = db.get("session", {})
    s["last_message_id"] = None
    db["session"] = s
    _save(db)


def add_tokens(prompt_tokens: int) -> None:
    """累加 prompt_tokens。"""
    if not prompt_tokens:
        return
    db = _load()
    s = db.get("session", {})
    s["prompt_tokens"] = s.get("prompt_tokens", 0) + prompt_tokens
    s["last_used"] = time.time()
    db["session"] = s
    _save(db)


def get_current_session_id() -> str:
    """获取当前活跃的 session_id。"""
    db = _load()
    return db.get("session", {}).get("session_id", "")

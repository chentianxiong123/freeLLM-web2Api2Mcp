"""多账号管理

存储：proxy/accounts.json
[
    {
        "id": "acc_001",
        "label": "主账号",
        "login_type": "email",
        "account": "user@example.com",
        "password": "...",
        "token": "...",
        "session_id": "...",
        "headers": {...},
        "active": true,
        "created_at": 1234567890,
        "last_used": 1234567890
    }
]
"""

import json
import time
import threading
from pathlib import Path

_FILE = Path(__file__).parent / "accounts.json"
_LOCK = threading.Lock()


def _load() -> list[dict]:
    with _LOCK:
        if not _FILE.exists():
            return []
        try:
            return json.loads(_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []


def _save(data: list[dict]) -> None:
    with _LOCK:
        _FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def list_accounts() -> list[dict]:
    """列出所有账号（不含密码）。"""
    accounts = _load()
    return [
        {k: v for k, v in acc.items() if k != "password" and k != "headers"}
        for acc in accounts
    ]


def get_account_by_id(acc_id: str) -> dict | None:
    """按 ID 查找账号（含敏感字段）。"""
    for acc in _load():
        if acc.get("id") == acc_id:
            return acc
    return None


def get_active_account() -> dict | None:
    """获取当前活跃账号（含 token/headers，用于 API 调用）。"""
    accounts = _load()
    for acc in accounts:
        if acc.get("active"):
            return acc
    return accounts[0] if accounts else None


def get_account_config() -> dict:
    """获取当前活跃账号，返回旧版 config 格式（兼容 deepseek_api.py）。"""
    acc = get_active_account()
    if not acc:
        return {}
    return {
        "id": acc.get("id", ""),
        "token": acc.get("token", ""),
        "session_id": acc.get("session_id", ""),
        "headers": acc.get("headers", {}),
        "cookie": "",
        "login_type": acc.get("login_type", ""),
        "_password": acc.get("password", ""),
        "_email": acc.get("account", "") if acc.get("login_type") == "email" else "",
        "_mobile": acc.get("account", "") if acc.get("login_type") == "phone" else "",
    }


def add_account(label: str, login_type: str, account: str, password: str) -> dict:
    """添加新账号。"""
    accounts = _load()
    now = int(time.time())

    # 生成 ID
    existing_nums = []
    for acc in accounts:
        aid = acc.get("id", "")
        if aid.startswith("acc_"):
            try:
                existing_nums.append(int(aid[4:]))
            except ValueError:
                pass
    next_num = (max(existing_nums) + 1) if existing_nums else 1
    new_id = f"acc_{next_num:03d}"

    new_acc = {
        "id": new_id,
        "label": label or f"账号{next_num}",
        "login_type": login_type,
        "account": account,
        "password": password,
        "token": "",
        "session_id": "",
        "headers": {},
        "active": len(accounts) == 0,  # 第一个账号自动激活
        "created_at": now,
        "last_used": now,
    }
    accounts.append(new_acc)
    _save(accounts)
    return {k: v for k, v in new_acc.items() if k != "password" and k != "headers"}


def update_account(acc_id: str, patch: dict) -> dict | None:
    """更新账号信息。"""
    accounts = _load()
    for acc in accounts:
        if acc.get("id") == acc_id:
            for k in ("label", "login_type", "account", "password", "token", "session_id", "headers", "active"):
                if k in patch:
                    acc[k] = patch[k]
            acc["updated_at"] = int(time.time())
            _save(accounts)
            return {k: v for k, v in acc.items() if k != "password" and k != "headers"}
    return None


def delete_account(acc_id: str) -> bool:
    """删除账号。"""
    accounts = _load()
    new_accounts = [a for a in accounts if a.get("id") != acc_id]
    if len(new_accounts) == len(accounts):
        return False
    # 如果删除的是活跃账号，激活第一个
    if any(a.get("active") for a in accounts if a.get("id") == acc_id):
        if new_accounts:
            new_accounts[0]["active"] = True
    _save(new_accounts)
    return True


def activate_account(acc_id: str) -> bool:
    """切换活跃账号。"""
    accounts = _load()
    found = False
    for acc in accounts:
        if acc.get("id") == acc_id:
            acc["active"] = True
            acc["last_used"] = int(time.time())
            found = True
        else:
            acc["active"] = False
    if found:
        _save(accounts)
    return found


def save_account_token(acc_id: str, token: str, session_id: str, headers: dict) -> bool:
    """保存登录后的 token 和 session_id。"""
    accounts = _load()
    for acc in accounts:
        if acc.get("id") == acc_id:
            acc["token"] = token
            acc["session_id"] = session_id
            acc["headers"] = headers
            acc["last_used"] = int(time.time())
            _save(accounts)
            return True
    return False


def import_from_config() -> bool:
    """从旧版 config.json 导入账号（一次性迁移）。"""
    from config import load_config, CONFIG_PATH
    import shutil

    cfg = load_config()
    if not cfg.get("token"):
        return False

    accounts = _load()
    # 检查是否已导入
    for acc in accounts:
        if acc.get("token") == cfg.get("token"):
            return False

    now = int(time.time())
    new_acc = {
        "id": "acc_001",
        "label": "默认账号",
        "login_type": cfg.get("login_type", "email"),
        "account": cfg.get("_email", "") or cfg.get("_mobile", ""),
        "password": cfg.get("_password", ""),
        "token": cfg.get("token", ""),
        "session_id": cfg.get("session_id", ""),
        "headers": cfg.get("headers", {}),
        "active": True,
        "created_at": now,
        "last_used": now,
    }
    accounts.insert(0, new_acc)
    _save(accounts)
    return True

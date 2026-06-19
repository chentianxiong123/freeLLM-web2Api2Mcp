"""审批拦截器

请求/响应审批队列，用 asyncio.Event 实现异步阻塞等待。
"""

import asyncio
import json
import time
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PendingItem:
    """一条待审批项。"""
    id: int
    type: str  # "request" | "response"
    method: str
    path: str
    body: Any = None
    status: int = 0
    headers: dict = field(default_factory=dict)
    timestamp: float = 0.0
    duration_ms: float = 0.0
    conversion: dict = field(default_factory=dict)  # 转换结果
    # 审批
    event: asyncio.Event | None = None
    approved: bool | None = None  # True=放行, False=拒绝, None=待审批
    error: str = ""
    edited_body: Any = None  # 编辑后的 body


class ApprovalQueue:
    """审批队列。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._counter = 0
        self._enabled = False
        self._transparent = False  # 透明拦截模式：直接放行但留痕
        self._pending: dict[int, PendingItem] = {}
        self._history: list[PendingItem] = []
        self._max_history = 50

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, v: bool) -> None:
        self._enabled = v

    @property
    def transparent(self) -> bool:
        return self._transparent

    def set_transparent(self, v: bool) -> None:
        self._transparent = v

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    # ── 请求拦截 ──────────────────────────────────────

    async def intercept_request(self, method: str, path: str, body: Any = None, headers: dict | None = None, conversion: dict | None = None) -> dict:
        """拦截请求，阻塞等待审批。返回 {"action": "approve"/"reject"}。"""
        # 透明模式：直接放行但记录
        if self._transparent:
            item_id = self._next_id()
            item = PendingItem(
                id=item_id,
                type="request",
                method=method,
                path=path,
                body=self._truncate_body(body),
                headers=self._safe_dict(headers or {}),
                conversion=conversion or {},
                timestamp=time.time(),
                approved=True,
            )
            with self._lock:
                self._history_record(item)
            return {"action": "approve", "body": body}

        if not self._enabled:
            return {"action": "approve", "body": body}

        item_id = self._next_id()
        event = asyncio.Event()
        item = PendingItem(
            id=item_id,
            type="request",
            method=method,
            path=path,
            body=self._truncate_body(body),
            headers=self._safe_dict(headers or {}),
            conversion=conversion or {},
            timestamp=time.time(),
            event=event,
        )

        with self._lock:
            self._pending[item_id] = item

        # 阻塞等待前端操作
        await event.wait()

        # 取结果
        with self._lock:
            approved = item.approved
            error = item.error
            edited_body = item.edited_body
            self._history_record(item)
            self._pending.pop(item_id, None)

        if approved is False:
            return {"action": "reject", "error": error or "用户拒绝"}
        # 如果有编辑内容，使用编辑后的 body
        final_body = edited_body if edited_body is not None else body
        return {"action": "approve", "body": final_body, "edited": edited_body is not None}

    # ── 响应拦截 ──────────────────────────────────────

    async def intercept_response(self, request_item_id: int, status: int, body: Any = None, headers: dict | None = None, duration_ms: float = 0) -> dict:
        """拦截响应，阻塞等待审批。返回 {"action": "approve"/"reject"}。"""
        # 透明模式：直接放行但记录
        if self._transparent:
            resp_id = self._next_id()
            item = PendingItem(
                id=resp_id,
                type="response",
                method="",
                path=f"#{request_item_id} 响应",
                body=self._truncate_body(body),
                status=status,
                headers=self._safe_dict(headers or {}),
                timestamp=time.time(),
                duration_ms=duration_ms,
                approved=True,
            )
            with self._lock:
                self._history_record(item)
            return {"action": "approve", "body": body}

        if not self._enabled:
            return {"action": "approve", "body": body}

        resp_id = self._next_id()
        event = asyncio.Event()
        item = PendingItem(
            id=resp_id,
            type="response",
            method="",
            path=f"#{request_item_id} 响应",
            body=self._truncate_body(body),
            status=status,
            headers=self._safe_dict(headers or {}),
            timestamp=time.time(),
            duration_ms=duration_ms,
            event=event,
        )

        with self._lock:
            self._pending[resp_id] = item

        await event.wait()

        with self._lock:
            approved = item.approved
            error = item.error
            edited_body = item.edited_body
            self._history_record(item)
            self._pending.pop(resp_id, None)

        if approved is False:
            return {"action": "reject", "error": error or "用户拒绝"}
        # 如果有编辑内容，使用编辑后的 body
        final_body = edited_body if edited_body is not None else body
        return {"action": "approve", "body": final_body, "edited": edited_body is not None}

    # ── 前端操作 ──────────────────────────────────────

    def approve(self, item_id: int) -> bool:
        """放行。"""
        with self._lock:
            item = self._pending.get(item_id)
            if not item or not item.event:
                return False
            item.approved = True
            item.event.set()
        return True

    def edit_item(self, item_id: int, edited_body: Any) -> bool:
        """编辑待审批项的 body。"""
        with self._lock:
            item = self._pending.get(item_id)
            if not item:
                return False
            item.edited_body = edited_body
        return True

    def reject(self, item_id: int, error: str = "") -> bool:
        """拒绝。"""
        with self._lock:
            item = self._pending.get(item_id)
            if not item or not item.event:
                return False
            item.approved = False
            item.error = error
            item.event.set()
        return True

    def approve_all(self) -> int:
        """放行所有。"""
        count = 0
        with self._lock:
            for item in self._pending.values():
                if item.event and item.approved is None:
                    item.approved = True
                    item.event.set()
                    count += 1
        return count

    # ── 查询 ──────────────────────────────────────

    def list_pending(self) -> list[dict]:
        with self._lock:
            return [self._to_dict(item) for item in self._pending.values()]

    def list_history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [self._to_dict(item) for item in self._history[:limit]]

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()

    def clear_all(self) -> None:
        with self._lock:
            self._pending.clear()
            self._history.clear()

    # ── 内部 ──────────────────────────────────────

    def _truncate_body(self, body: Any) -> Any:
        if body is None:
            return None
        if isinstance(body, (str, int, float, bool)):
            return body
        try:
            text = json.dumps(body, ensure_ascii=False, default=str)
            if len(text) > 10000:
                return {"_truncated": text[:10000] + "...(共" + str(len(text)) + "字符)"}
        except Exception:
            pass
        return body

    def _safe_dict(self, d: dict) -> dict:
        safe = {}
        for k, v in d.items():
            sv = str(v)
            if k.lower() in ("authorization", "cookie", "x-ds-pow-response"):
                safe[k] = sv[:20] + "..." if len(sv) > 20 else sv
            else:
                safe[k] = sv[:200]
        return safe

    def _history_record(self, item: PendingItem) -> None:
        item.event = None  # Event 不可序列化
        self._history.insert(0, item)
        if len(self._history) > self._max_history:
            self._history = self._history[:self._max_history]

    def _to_dict(self, item: PendingItem) -> dict:
        return {
            "id": item.id,
            "type": item.type,
            "method": item.method,
            "path": item.path,
            "body": item.body,
            "status": item.status,
            "headers": item.headers,
            "conversion": item.conversion,
            "timestamp": item.timestamp,
            "duration_ms": round(item.duration_ms, 1),
            "approved": item.approved,
            "error": item.error,
            "edited_body": item.edited_body,
        }


# 全局单例
queue = ApprovalQueue()

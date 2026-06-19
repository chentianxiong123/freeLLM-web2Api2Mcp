"""调试拦截器

捕获所有请求/响应，用于调试和可视化。
"""

import json
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InterceptedRequest:
    """一条被拦截的请求。"""
    id: int
    method: str
    path: str
    request_body: Any = None
    request_headers: dict = field(default_factory=dict)
    response_status: int = 0
    response_body: Any = None
    response_headers: dict = field(default_factory=dict)
    timestamp: float = 0.0
    duration_ms: float = 0.0
    error: str = ""


class DebugInterceptor:
    """请求/响应拦截器，存储最近 N 条记录。"""

    def __init__(self, max_size: int = 100):
        self._records: deque[InterceptedRequest] = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._counter = 0
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, v: bool) -> None:
        self._enabled = v

    def start_request(self, method: str, path: str, body: Any = None, headers: dict | None = None) -> InterceptedRequest:
        """开始记录一个请求。"""
        if not self._enabled:
            return InterceptedRequest(id=0, method=method, path=path)

        with self._lock:
            self._counter += 1
            rec = InterceptedRequest(
                id=self._counter,
                method=method,
                path=path,
                request_body=self._safe_body(body),
                request_headers=self._safe_headers(headers or {}),
                timestamp=time.time(),
            )
            self._records.appendleft(rec)
            return rec

    def finish_request(self, rec: InterceptedRequest, status: int = 200, body: Any = None, headers: dict | None = None, error: str = "") -> None:
        """完成记录。"""
        if not self._enabled or rec.id == 0:
            return
        rec.response_status = status
        rec.response_body = self._safe_body(body)
        rec.response_headers = self._safe_headers(headers or {})
        rec.duration_ms = (time.time() - rec.timestamp) * 1000
        rec.error = error

    def add_custom(self, name: str, data: Any) -> None:
        """添加自定义调试记录（用于转换可视化）。"""
        if not self._enabled:
            return
        with self._lock:
            self._counter += 1
            rec = InterceptedRequest(
                id=self._counter,
                method="DEBUG",
                path=name,
                request_body=self._safe_body(data),
                timestamp=time.time(),
            )
            self._records.appendleft(rec)

    def list_records(self, limit: int = 50) -> list[dict]:
        """列出最近的记录。"""
        with self._lock:
            return [self._to_dict(r) for r in list(self._records)[:limit]]

    def get_record(self, rec_id: int) -> dict | None:
        """获取单条记录详情。"""
        with self._lock:
            for r in self._records:
                if r.id == rec_id:
                    return self._to_dict(r)
        return None

    def clear(self) -> None:
        """清空记录。"""
        with self._lock:
            self._records.clear()

    def _safe_body(self, body: Any) -> Any:
        """安全序列化 body（避免大 body 占用太多内存）。"""
        if body is None:
            return None
        if isinstance(body, (str, int, float, bool)):
            return body
        try:
            text = json.dumps(body, ensure_ascii=False, default=str)
            if len(text) > 10000:
                return text[:10000] + "...(truncated)"
            return body
        except Exception:
            return str(body)[:1000]

    def _safe_headers(self, headers: dict) -> dict:
        """安全处理 headers（隐藏敏感信息）。"""
        safe = {}
        for k, v in headers.items():
            if k.lower() in ("authorization", "cookie", "x-ds-pow-response"):
                safe[k] = v[:20] + "..." if len(str(v)) > 20 else v
            else:
                safe[k] = v
        return safe

    def _to_dict(self, rec: InterceptedRequest) -> dict:
        return {
            "id": rec.id,
            "method": rec.method,
            "path": rec.path,
            "request_body": rec.request_body,
            "request_headers": rec.request_headers,
            "response_status": rec.response_status,
            "response_body": rec.response_body,
            "response_headers": rec.response_headers,
            "timestamp": rec.timestamp,
            "duration_ms": round(rec.duration_ms, 1),
            "error": rec.error,
        }


# 全局单例
interceptor = DebugInterceptor()

"""调度核心：会话亲和 + 加权轮换 + 冷却 + 缓存路由 + 串行队列。

按 CLIProxyAPI 蓝图（SessionAffinity / WeightedRoundRobin / cooldown / eligibility）+ 用户调度策略：
- 严格串行：一次只处理一个请求（绝不并发）
- 会话亲和：consumer+platform → conversation_id（同消费者同会话续聊）
- 加权轮换：多供应商平滑加权轮换（降风控）
- 冷却：平台错误（408/5xx）→ 冷却期不选该平台
- 缓存路由：key=consumer+platform+hash(prompt) 命中直接返回（不调 LLM）
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field

# ============ 会话亲和（SessionAffinity）============
class SessionAffinity:
    """consumer+platform → conversation_id 映射（同消费者同会话），TTL 回收。"""

    def __init__(self, ttl: float = 1800) -> None:
        self._ttl = ttl
        self._m: dict[str, tuple[str, float]] = {}  # key -> (cid, last_used)
        self._lock = threading.Lock()

    @staticmethod
    def _key(consumer: str, platform: str) -> str:
        return f"{consumer}\x1f{platform}"

    def get(self, consumer: str, platform: str) -> str | None:
        """取该消费者+平台的会话（未过期），续聊用。"""
        key = self._key(consumer, platform)
        with self._lock:
            hit = self._m.get(key)
            if not hit:
                return None
            cid, used = hit
            if time.time() - used > self._ttl:
                del self._m[key]
                return None
            self._m[key] = (cid, time.time())
            return cid

    def set(self, consumer: str, platform: str, cid: str) -> None:
        key = self._key(consumer, platform)
        with self._lock:
            self._m[key] = (cid, time.time())
            if len(self._m) > 4096:  # 防无限增长
                self._gc()

    def _gc(self) -> None:
        now = time.time()
        expired = [k for k, (_, used) in self._m.items() if now - used > self._ttl]
        for k in expired:
            del self._m[k]

    def size(self) -> int:
        with self._lock:
            return len(self._m)


# ============ 平滑加权轮换（WeightedRoundRobin）============
class WeightedRoundRobin:
    """多供应商平滑加权轮换（nginx smooth weighted round-robin）。

    weight>0 才参与；weight=0 排除；候选带 weight 权重。
    """

    def __init__(self) -> None:
        self._state: dict[str, list[int]] = {}  # key -> [current, weight]
        self._lock = threading.Lock()

    def _key(self, provider: str, model: str) -> str:
        return f"{provider}\x1f{model}"

    def pick(self, candidates: dict[str, int], model: str = "") -> str | None:
        """从 {provider: weight} 候选里平滑加权选一个，返回 provider。"""
        positive = {p: w for p, w in candidates.items() if w > 0}
        if not positive:
            return None
        total = sum(positive.values())
        best, best_key = None, None
        with self._lock:
            for provider, weight in positive.items():
                key = self._key(provider, model)
                st = self._state.setdefault(key, [0, weight])
                st[0] += weight
                if best is None or st[0] > self._state[self._key(best, model)][0]:
                    best, best_key = provider, key
            if best is not None:
                self._state[best_key][0] -= total
                if len(self._state) > 4096:
                    self._state.clear()
        return best

    def reset(self, provider: str) -> None:
        with self._lock:
            for key in list(self._state):
                if key.split("\x1f")[0] == provider:
                    del self._state[key]


# ============ 冷却（Cooldown）============
class Cooldown:
    """平台错误冷却：mark_error 后冷却 cooldown_sec 不选该平台。"""

    def __init__(self, cooldown_sec: float = 300) -> None:
        self._cooldown = cooldown_sec
        self._m: dict[str, float] = {}  # platform -> until
        self._lock = threading.Lock()

    def mark_error(self, platform: str, cooldown_sec: float | None = None) -> None:
        sec = cooldown_sec if cooldown_sec is not None else self._cooldown
        with self._lock:
            self._m[platform] = time.time() + sec

    def is_cooling(self, platform: str) -> bool:
        with self._lock:
            until = self._m.get(platform)
            if until is None:
                return False
            if time.time() > until:
                del self._m[platform]
                return False
            return True

    def clear(self, platform: str) -> None:
        with self._lock:
            self._m.pop(platform, None)


# ============ 缓存路由（CacheRoute）============
class CacheRoute:
    """key=consumer+platform+hash(prompt) → answer，TTL。命中直接返回（不调 LLM）。"""

    def __init__(self, ttl: float = 600) -> None:
        self._ttl = ttl
        self._m: dict[str, tuple[str, float]] = {}  # key -> (answer, ts)
        self._lock = threading.Lock()

    @staticmethod
    def make_key(consumer: str, platform: str, prompt: str) -> str:
        h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        return f"{consumer}\x1f{platform}\x1f{h}"

    def get(self, key: str) -> str | None:
        with self._lock:
            hit = self._m.get(key)
            if not hit:
                return None
            answer, ts = hit
            if time.time() - ts > self._ttl:
                del self._m[key]
                return None
            return answer

    def set(self, key: str, answer: str) -> None:
        with self._lock:
            self._m[key] = (answer, time.time())
            if len(self._m) > 4096:
                now = time.time()
                for k in [k for k, (_, ts) in self._m.items() if now - ts > self._ttl]:
                    del self._m[k]


# ============ 串行队列（SerialQueue）============
class SerialQueue:
    """严格串行：一次只执行一个任务（绝不并发）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def acquire(self) -> None:
        self._lock.acquire()

    def release(self) -> None:
        self._lock.release()

    def __enter__(self) -> "SerialQueue":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


# ============ 调度器（聚合以上）============
@dataclass
class RouteDecision:
    """调度决策结果。"""
    platform: str
    conversation_id: str = ""
    cached: bool = False
    answer: str = ""


class Scheduler:
    """调度器：缓存路由 → 会话亲和 → 平台轮换(排除冷却) → 串行执行。"""

    def __init__(
        self,
        affinity_ttl: float = 1800,
        cache_ttl: float = 600,
        cooldown_sec: float = 300,
    ) -> None:
        self.affinity = SessionAffinity(affinity_ttl)
        self.rr = WeightedRoundRobin()
        self.cooldown = Cooldown(cooldown_sec)
        self.cache = CacheRoute(cache_ttl)
        self.queue = SerialQueue()

    # ---- 路由（选平台 + 会话亲和 + 缓存）----
    def route(
        self,
        consumer: str,
        platform: str,
        prompt: str,
        enabled: dict[str, bool] | None = None,
        weights: dict[str, int] | None = None,
    ) -> RouteDecision:
        """调度一个请求：
        1) 缓存命中 → 直接返回 cached
        2) 选平台（加权轮换，排除冷却/禁用）
        3) 会话亲和（consumer+platform → cid 续聊）
        """
        # 缓存路由
        cache_key = self.cache.make_key(consumer, platform, prompt)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return RouteDecision(platform, cached=True, answer=cached)

        # 选平台
        if platform == "auto":
            platform = self._pick_platform(enabled or {}, weights or {})
            if not platform:
                return RouteDecision(platform, conversation_id="")
        elif platform:
            if (enabled and not enabled.get(platform, True)) or self.cooldown.is_cooling(platform):
                platform = self._pick_platform(enabled or {}, weights or {}) or platform

        # 会话亲和
        cid = self.affinity.get(consumer, platform)
        return RouteDecision(platform, conversation_id=cid or "")

    def _pick_platform(
        self, enabled: dict[str, bool], weights: dict[str, int]
    ) -> str | None:
        """从启用且未冷却的平台里加权轮换选一个。"""
        candidates = {}
        for platform, on in enabled.items():
            if on and not self.cooldown.is_cooling(platform):
                candidates[platform] = weights.get(platform, 1)
        return self.rr.pick(candidates)

    # ---- 结果回写 ----
    def commit(
        self,
        consumer: str,
        platform: str,
        prompt: str,
        conversation_id: str,
        answer: str,
    ) -> None:
        """执行成功后：写缓存 + 更新会话亲和 + 清冷却。"""
        key = self.cache.make_key(consumer, platform, prompt)
        if answer:
            self.cache.set(key, answer)
        if conversation_id:
            self.affinity.set(consumer, platform, conversation_id)
        self.cooldown.clear(platform)

    def on_error(self, platform: str, cooldown_sec: float | None = None) -> None:
        """平台错误：冷却该平台（降风控）。"""
        self.cooldown.mark_error(platform, cooldown_sec)


# 全局调度器实例
scheduler = Scheduler()

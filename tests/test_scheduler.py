"""调度核心单元测试：会话亲和/加权轮换/冷却/缓存路由/串行队列/调度器。"""
import time

from tutor.scheduler import (
    CacheRoute,
    Cooldown,
    RouteDecision,
    Scheduler,
    SerialQueue,
    SessionAffinity,
    WeightedRoundRobin,
)


# ---- 会话亲和 ----
def test_session_affinity_set_get():
    a = SessionAffinity(ttl=60)
    assert a.get("c1", "deepseek") is None
    a.set("c1", "deepseek", "abc123")
    assert a.get("c1", "deepseek") == "abc123"
    assert a.get("c2", "deepseek") is None  # 不同消费者隔离


def test_session_affinity_ttl():
    a = SessionAffinity(ttl=0.1)
    a.set("c1", "kimi", "xyz")
    assert a.get("c1", "kimi") == "xyz"
    time.sleep(0.15)
    assert a.get("c1", "kimi") is None  # 过期回收


def test_session_affinity_multi_platform():
    a = SessionAffinity(ttl=60)
    a.set("c1", "deepseek", "cid-ds")
    a.set("c1", "doubao", "cid-db")
    assert a.get("c1", "deepseek") == "cid-ds"
    assert a.get("c1", "doubao") == "cid-db"  # 同消费者每平台各一


# ---- 加权轮换 ----
def test_weighted_rr_round_robin():
    rr = WeightedRoundRobin()
    picks = [rr.pick({"a": 1, "b": 1, "c": 1}) for _ in range(9)]
    assert set(picks) == {"a", "b", "c"}  # 都参与
    assert len(set(picks)) == 3


def test_weighted_rr_weight_distribution():
    rr = WeightedRoundRobin()
    picks = [rr.pick({"a": 3, "b": 1}) for _ in range(40)]
    # 平滑加权：权重 3:1 → a 约 3/4
    assert picks.count("a") > picks.count("b") * 2


def test_weighted_rr_zero_weight_excluded():
    rr = WeightedRoundRobin()
    assert rr.pick({"a": 0, "b": 1}) == "b"  # 权重 0 排除
    assert rr.pick({"a": 0}) is None


# ---- 冷却 ----
def test_cooldown_mark_is_cooling():
    c = Cooldown(cooldown_sec=60)
    assert not c.is_cooling("deepseek")
    c.mark_error("deepseek")
    assert c.is_cooling("deepseek")
    c.clear("deepseek")
    assert not c.is_cooling("deepseek")


def test_cooldown_expire():
    c = Cooldown(cooldown_sec=0.1)
    c.mark_error("kimi")
    assert c.is_cooling("kimi")
    time.sleep(0.15)
    assert not c.is_cooling("kimi")  # 到期恢复


# ---- 缓存路由 ----
def test_cache_route_hit():
    cr = CacheRoute(ttl=60)
    key = cr.make_key("c1", "deepseek", "hello")
    assert cr.get(key) is None
    cr.set(key, "answer-1")
    assert cr.get(key) == "answer-1"


def test_cache_route_ttl():
    cr = CacheRoute(ttl=0.1)
    key = cr.make_key("c1", "kimi", "hi")
    cr.set(key, "a")
    time.sleep(0.15)
    assert cr.get(key) is None  # 过期


def test_cache_key_isolated():
    assert CacheRoute.make_key("c1", "a", "p") != CacheRoute.make_key("c2", "a", "p")
    assert CacheRoute.make_key("c1", "a", "p") != CacheRoute.make_key("c1", "b", "p")


# ---- 串行队列 ----
def test_serial_queue():
    q = SerialQueue()
    assert q.acquire() is None
    q.release()


# ---- 调度器 ----
def test_scheduler_cache_route():
    s = Scheduler(cache_ttl=60)
    s.cache.set(s.cache.make_key("c1", "deepseek", "q"), "cached-answer")
    d = s.route("c1", "deepseek", "q")
    assert d.cached and d.answer == "cached-answer"


def test_scheduler_affinity_commit():
    s = Scheduler(affinity_ttl=60)
    d = s.route("c1", "deepseek", "q2", enabled={"deepseek": True})
    assert not d.cached
    s.commit("c1", "deepseek", "q2", "cid-42", "answer-42")
    d2 = s.route("c1", "deepseek", "q3", enabled={"deepseek": True})
    assert d2.conversation_id == "cid-42"  # 会话亲和：续聊


def test_scheduler_cooldown_excludes():
    s = Scheduler(cooldown_sec=60)
    s.on_error("deepseek")  # 冷却 deepseek
    # auto 轮换：deepseek 冷却排除，选 doubao
    d = s.route("c1", "auto", "q4", enabled={"deepseek": True, "doubao": True})
    assert d.platform == "doubao"


def test_scheduler_disabled_excluded():
    s = Scheduler()
    d = s.route("c1", "auto", "q5", enabled={"deepseek": False, "doubao": True})
    assert d.platform == "doubao"  # deepseek 禁用排除

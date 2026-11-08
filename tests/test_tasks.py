"""轮询任务单元测试：TaskStore 生命周期 / TTL / submit 返回 task_id。"""
import time

from tutor.tasks import TaskStore, get_task, submit


def test_task_store_lifecycle():
    ts = TaskStore()
    tid = ts.create()
    assert ts.get(tid)["status"] == "pending"
    ts.update(tid, status="done", result={"answer": "hi"})
    t = ts.get(tid)
    assert t["status"] == "done"
    assert t["result"]["answer"] == "hi"


def test_task_store_error():
    ts = TaskStore()
    tid = ts.create()
    ts.update(tid, status="error", error="boom")
    t = ts.get(tid)
    assert t["status"] == "error"
    assert t["error"] == "boom"


def test_task_store_ttl():
    ts = TaskStore(ttl=0.1)
    tid = ts.create()
    time.sleep(0.15)
    assert ts.get(tid) is None  # 过期回收


def test_submit_returns_task_id():
    tid = submit("deepseek", "hello")
    assert isinstance(tid, str) and len(tid) == 16
    t = get_task(tid)
    assert t is not None
    assert t["status"] in ("pending", "running", "error")  # 后台串行执行

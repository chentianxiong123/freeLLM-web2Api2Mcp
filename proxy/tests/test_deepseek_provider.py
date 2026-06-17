"""DeepSeekProvider 烟雾测试。

模拟 ds_api.chat_completion 被 monkey-patch 成同步 generator，
验证 DeepSeekProvider.chat() 的 Event 翻译是否正确。

不依赖真实 DeepSeek 网络连接，单元级别验证 Provider 的语义。
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from providers.base import Event
from providers.deepseek import DeepSeekProvider


# ── 模拟生成器：返回一段真实 DeepSeek 流（content + tool block + done）──


def fake_ds_chat_completion(cfg, messages, **kwargs):
    """模拟 ds_api.chat_completion 的同步 generator。"""
    yield ("thinking", "用户想看桌面。")
    yield ("content", "好的，我列文件：\n\n工具 Bash\n")
    yield ("content", 'command="ls -la"\n')
    yield ("content", "工具结束\n")
    yield ("token_usage", 120)
    yield ("message_id", 99999)
    yield ("done", None)


# ── 测试 1：成功流 → 5+ 个 Event + done 收尾 ─────────────


def test_deepseek_provider_emits_events():
    """DeepSeekProvider.chat() 把同步生成器 → 异步 Event 流。"""
    import deepseek_api as ds_api
    orig = ds_api.chat_completion
    ds_api.chat_completion = fake_ds_chat_completion
    try:
        async def run():
            provider = DeepSeekProvider()
            events = []
            async for ev in provider.chat(
                [{"role": "user", "content": "看桌面"}],
                model="deepseek-v4-flash",
            ):
                events.append(ev)
            return events

        events = asyncio.run(run())

        # 至少要有：thinking / content（多次） / token_usage / message_id / done
        types = [e.type for e in events]
        print(f"  Event types: {types}")
        assert "thinking" in types, "必须有 thinking"
        assert "content" in types, "必须有 content"
        assert "done" in types, "必须有 done"
        assert types[-1] == "done", f"done 应在最后，实际: {types[-1]}"

        # content 累积起来 = "好的，我列文件：\n\n工具 Bash\ncommand=\"ls -la\"\n工具结束\n"
        full_content = "".join(e.val for e in events if e.type == "content")
        print(f"  Full content: {full_content!r}")
        assert "工具 Bash" in full_content
        assert "工具结束" in full_content
        assert 'command="ls -la"' in full_content

        # token_usage 透传
        usage = [e for e in events if e.type == "token_usage"]
        assert usage and usage[0].val == 120, f"token_usage 错: {usage}"

        # message_id 透传
        mid = [e for e in events if e.type == "message_id"]
        assert mid and mid[0].val == 99999, f"message_id 错: {mid}"
    finally:
        ds_api.chat_completion = orig


# ── 测试 2：未登录 → error 事件 ──────────────────────


def test_deepseek_provider_no_token():
    """config 里没 token → 立即 yield error 事件。"""
    import config as cfg_module
    orig = cfg_module.load_config

    def fake_load():
        return {"token": "", "session_id": "fake"}

    cfg_module.load_config = fake_load
    try:
        async def run():
            provider = DeepSeekProvider()
            events = []
            async for ev in provider.chat(
                [{"role": "user", "content": "x"}],
            ):
                events.append(ev)
            return events

        events = asyncio.run(run())
        assert len(events) == 1, f"应只有 1 个事件: {events}"
        assert events[0].type == "error", f"应是 error: {events[0]}"
        assert "未登录" in events[0].val.get("message", ""), f"错误消息: {events[0]}"
    finally:
        cfg_module.load_config = orig


# ── 测试 3：错误流 → error 事件 ──────────────────────


def test_deepseek_provider_error_stream():
    """ds_api 抛 error tuple → 透传成 Event('error', ...)。"""
    import deepseek_api as ds_api

    def fake_err(cfg, messages, **kwargs):
        yield ("error", {"message": "DeepSeek 502"})

    orig = ds_api.chat_completion
    ds_api.chat_completion = fake_err
    try:
        async def run():
            provider = DeepSeekProvider()
            events = []
            async for ev in provider.chat(
                [{"role": "user", "content": "x"}],
            ):
                events.append(ev)
            return events

        events = asyncio.run(run())
        assert len(events) == 1, f"应只有 1 个事件: {events}"
        assert events[0].type == "error"
        assert "502" in events[0].val.get("message", "")
    finally:
        ds_api.chat_completion = orig


# ── 测试 4：model 名 → model_type 映射 ────────────────


def test_model_type_resolution():
    """OpenAI model 名要正确映射成 DeepSeek model_type。"""
    p = DeepSeekProvider()
    assert p._resolve_model_type("deepseek-v4-flash") == "default"
    assert p._resolve_model_type("deepseek-v4-pro") == "expert"
    assert p._resolve_model_type(None) == "default"
    assert p._resolve_model_type("unknown") == "default"


# ── 跑全部 ──────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_deepseek_provider_emits_events,
        test_deepseek_provider_no_token,
        test_deepseek_provider_error_stream,
        test_model_type_resolution,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
    print()
    if failed:
        print(f"❌ {failed}/{len(tests)} 失败")
        sys.exit(1)
    else:
        print(f"✅ {len(tests)}/{len(tests)} 通过")

"""端到端集成测试：DeepSeekProvider → stream_events_to_openai → SSE。

模拟 ds_api 输出（带工具块）→ DeepSeekProvider.chat() →
stream_events_to_openai() → 解析 SSE → 验证完整管道满足 7 条不变式。
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from providers.base import Event
from providers.deepseek import DeepSeekProvider
from core.react_loop import stream_events_to_openai


def fake_ds_with_tool(cfg, messages, **kwargs):
    """模拟 DS 真实输出：thinking + 内容 + 工具块。"""
    yield ("thinking", "用户想看桌面。")
    yield ("content", "好的，我列文件：\n\n")
    yield ("content", "工具 Bash\n")
    yield ("content", 'command="ls -la C:/Users/a1/Desktop"\n')
    yield ("content", "工具结束\n")
    yield ("token_usage", 156)
    yield ("done", None)


def fake_ds_text_only(cfg, messages, **kwargs):
    """模拟 DS 纯文本输出。"""
    yield ("content", "你好，")
    yield ("content", "我是 DeepSeek")
    yield ("done", None)


def parse_sse(text: str) -> list[dict]:
    chunks = []
    for line in text.split("\n"):
        if not line.startswith("data: "):
            continue
        s = line[6:].strip()
        if s == "[DONE]":
            chunks.append({"_done": True})
            continue
        try:
            chunks.append(json.loads(s))
        except json.JSONDecodeError:
            pass
    return chunks


# ── 测试 1：DeepSeek 流带工具块 → SSE 满足 7 条不变式 ─────


def test_ds_provider_with_tool_calls_full_pipe():
    """DeepSeekProvider → stream_events_to_openai → SSE 完整链路。"""
    import deepseek_api as ds_api
    orig = ds_api.chat_completion
    ds_api.chat_completion = fake_ds_with_tool
    try:
        async def run():
            provider = DeepSeekProvider()
            events = provider.chat(
                [{"role": "user", "content": "看桌面"}],
                model="deepseek-v4-flash",
            )
            chunks = []
            async for sse in stream_events_to_openai(
                events,
                request_id="chatcmpl-integ",
                model="deepseek-v4-flash",
                tools_schema=[{
                    "type": "function",
                    "function": {
                        "name": "Bash",
                        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
                    },
                }],
            ):
                chunks.append(sse)
            return "".join(chunks)

        full = asyncio.run(run())
        chunks = parse_sse(full)
        chunks = [c for c in chunks if not c.get("_done")]

        # 不变式 ②：content 留空
        content_deltas = [c for c in chunks if c["choices"][0]["delta"].get("content")]
        assert not content_deltas, f"有工具块时 content 必须留空: {content_deltas}"

        # 不变式 ③：role delta 必发
        first = chunks[0]["choices"][0]["delta"]
        assert "role" in first, f"缺 role: {first}"

        # 不变式 ⑦：tool_calls delta 必有
        tc_chunks = [c for c in chunks if c["choices"][0]["delta"].get("tool_calls")]
        assert tc_chunks, "缺 tool_calls delta"
        first_tc = tc_chunks[0]["choices"][0]["delta"]["tool_calls"][0]
        assert first_tc.get("id", "").startswith("call_")
        assert first_tc["function"]["name"] == "Bash"

        # 不变式 ①：finish_reason=tool_calls
        last = chunks[-1]
        assert last["choices"][0]["finish_reason"] == "tool_calls"

        # 不变式 ⑥：tool_call_id 稳定
        ids = [tc["id"] for c in tc_chunks for tc in c["choices"][0]["delta"]["tool_calls"] if "id" in tc]
        assert ids, "缺 id"
        assert len(set(ids)) == 1, f"id 不稳定: {ids}"

        # 额外：参数有内容
        all_args = "".join(
            tc.get("function", {}).get("arguments", "")
            for c in tc_chunks
            for tc in c["choices"][0]["delta"]["tool_calls"]
        )
        assert "ls -la" in all_args, f"参数应包含 ls -la: {all_args!r}"
    finally:
        ds_api.chat_completion = orig


# ── 测试 2：DeepSeek 纯文本 → SSE 满足 ① ───────────────


def test_ds_provider_text_only_full_pipe():
    """DeepSeekProvider 纯文本 → finish_reason=stop。"""
    import deepseek_api as ds_api
    orig = ds_api.chat_completion
    ds_api.chat_completion = fake_ds_text_only
    try:
        async def run():
            provider = DeepSeekProvider()
            events = provider.chat([{"role": "user", "content": "x"}])
            chunks = []
            async for sse in stream_events_to_openai(
                events, request_id="chatcmpl-t", model="deepseek-v4-flash"
            ):
                chunks.append(sse)
            return "".join(chunks)

        full = asyncio.run(run())
        chunks = parse_sse(full)
        chunks = [c for c in chunks if not c.get("_done")]

        full_text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c.get("choices"))
        assert "你好" in full_text and "DeepSeek" in full_text, f"文本错: {full_text!r}"

        last = chunks[-1]
        assert last["choices"][0]["finish_reason"] == "stop"
    finally:
        ds_api.chat_completion = orig


# ── 跑全部 ──────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_ds_provider_with_tool_calls_full_pipe,
        test_ds_provider_text_only_full_pipe,
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

"""React 循环不变式单测。

这些测试钉死 7 条核心不变式（每一都对应一个曾经踩过的 bug）：

  ①  DeepSeek 发 stop 后，Claude Code 看到的 assistant 消息必含 finish_reason=stop
  ②  DeepSeek 发 tool_calls 后，content 必须留空（不污染 CC 看到的流）
  ③  第一次流任何东西之前，role delta 必发
  ④  react 续接时（body 含 tool role），只发工具结果原文给 DS
  ⑤  react 续接时，必须明确告诉 DS "这是工具回执"
  ⑥  tool_call_id 稳定传递
  ⑦  finish_reason=tool_calls 时，必须有 tool_calls delta

测试用 ScriptedProvider：脚本化按顺序返回 Event，方便断言边界条件。
"""

import asyncio
import json
import sys
from pathlib import Path

# 把 proxy 根目录加到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.react_loop import build_ds_input, stream_events_to_openai
from providers.base import Event, ProviderError
from providers.mock import ScriptedProvider


# ── 辅助：把 SSE 流解析成 chunk 列表 ──────────────────────


def parse_sse(sse_text: str) -> list[dict]:
    """把 SSE 文本解析成 chunk 列表。"""
    chunks = []
    for line in sse_text.split("\n"):
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


# ── 不变式 ①+②+③：DeepSeek 返回纯工具块 ────────────────


def test_streaming_with_tool_calls_empty_content():
    """DeepSeek 返 工具 Bash / 工具结束 块 → CC 看到的 content 必须留空。"""
    async def run():
        events = [
            # 模拟 DeepSeek 真实流：先 thinking → 写分析 → 写工具块
            Event("thinking", "让我列桌面"),
            Event("content", "好的，我让 Claude Code 查桌面。\n\n"),
            Event("content", "工具 Bash\n"),
            Event("content", 'command="ls -la C:/Users/a1/Desktop"\n'),
            Event("content", "工具结束\n"),
            Event("done", None),
        ]
        async def event_iter():
            for e in events:
                yield e

        sse_chunks = []
        async for sse in stream_events_to_openai(
            event_iter(),
            request_id="chatcmpl-test",
            model="deepseek-v4-flash",
            tools_schema=[{"type": "function", "function": {"name": "Bash", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}],
        ):
            sse_chunks.append(sse)

        full = "".join(sse_chunks)
        chunks = parse_sse(full)
        # 过滤掉 [DONE] 哨兵
        chunks = [c for c in chunks if not c.get("_done")]
        # 不变式 ②：content 必须留空（不流分析文字）
        content_chunks = [c for c in chunks if c.get("choices", [{}])[0].get("delta", {}).get("content")]
        assert not content_chunks, f"content 必须留空，实际流了: {content_chunks}"

        # 不变式 ③：第一个非 done chunk 必须是 role delta
        first_real = chunks[0] if chunks else None
        assert first_real, "至少要有一个 chunk"
        delta = first_real["choices"][0]["delta"]
        assert "role" in delta, f"第一个 chunk 缺 role: {first_real}"
        assert delta["role"] == "assistant", f"role 应是 assistant: {delta}"

        # 不变式 ⑦：必须有 tool_calls delta
        tool_call_chunks = [c for c in chunks if c["choices"][0]["delta"].get("tool_calls")]
        assert tool_call_chunks, "必须有 tool_calls delta"
        tc = tool_call_chunks[0]["choices"][0]["delta"]["tool_calls"][0]
        assert tc.get("id", "").startswith("call_"), f"tool_call id 必须以 call_ 开头: {tc}"
        assert tc.get("type") == "function", f"type 必须是 function: {tc}"
        assert tc.get("function", {}).get("name") == "Bash", f"工具名: {tc}"

        # 不变式 ①：finish_reason=tool_calls
        last = chunks[-1]  # 末条（不是 [DONE] 哨兵）
        fr = last["choices"][0].get("finish_reason")
        assert fr == "tool_calls", f"finish_reason 应是 tool_calls，实际: {fr}"

    asyncio.run(run())


# ── 不变式 ①：DeepSeek 返回纯文本（无工具块）────────────


def test_streaming_text_only_finish_stop():
    """DeepSeek 只返纯文本 → CC 看到 content + finish_reason=stop。"""
    async def run():
        events = [
            Event("content", "你好"),
            Event("content", "，我是"),
            Event("content", " DeepSeek"),
            Event("done", None),
        ]
        async def event_iter():
            for e in events:
                yield e

        sse_chunks = []
        async for sse in stream_events_to_openai(event_iter(), request_id="chatcmpl-test", model="deepseek-v4-flash", tools_schema=[]):
            sse_chunks.append(sse)

        chunks = parse_sse("".join(sse_chunks))
        chunks = [c for c in chunks if not c.get("_done")]

        # content 应该有
        full_content = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c.get("choices"))
        assert "你好" in full_content and "DeepSeek" in full_content, f"content 应包含原文: {full_content!r}"

        # finish_reason=stop
        last = chunks[-1]
        fr = last["choices"][0].get("finish_reason")
        assert fr == "stop", f"纯文本应 stop，实际: {fr}"

    asyncio.run(run())


# ── 不变式 ②+③：DeepSeek 整轮只 thinking 不 content ──────


def test_streaming_thinking_only_must_send_role():
    """DeepSeek 整轮只 thinking（无 content） → 仍然必须发 role delta。

    bug 场景：旧代码只在第一个 content 时发 role，整轮没 content 就漏发。
    """
    async def run():
        events = [
            Event("thinking", "思考中"),
            Event("thinking", "再想想"),
            Event("done", None),
        ]
        async def event_iter():
            for e in events:
                yield e

        sse_chunks = []
        async for sse in stream_events_to_openai(event_iter(), request_id="chatcmpl-test", model="deepseek-v4-flash", tools_schema=[]):
            sse_chunks.append(sse)

        chunks = parse_sse("".join(sse_chunks))
        chunks = [c for c in chunks if not c.get("_done")]
        # 必须有 role delta
        first_real = chunks[0] if chunks else None
        assert first_real, "至少要有一个 chunk"
        assert "role" in first_real["choices"][0]["delta"], f"必须发 role: {first_real}"

        # finish_reason=stop
        last = chunks[-1]
        fr = last["choices"][0].get("finish_reason")
        assert fr == "stop", f"应 stop，实际: {fr}"

    asyncio.run(run())


# ── 不变式 ④+⑤：react 续接 body 转 DS 消息 ───────────────


def test_react_continuation_only_tool_results():
    """body 含 tool role → 发给 DS 的 user content 必须只是工具结果，不带 user 原话。"""
    body = {
        "messages": [
            {"role": "user", "content": "看桌面有什么？"},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_xyz789",
                "type": "function",
                "function": {"name": "Bash", "arguments": '{"command": "ls"}'},
            }]},
            {"role": "tool", "tool_call_id": "call_xyz789", "content": "111.txt\nfoo.txt"},
            {"role": "user", "content": "看桌面有什么？"},  # CC 续接时也带上
        ]
    }

    req = build_ds_input(body)

    # 不变式 ④：user 原话 "看桌面有什么？" 绝对不能出现在发 DS 的内容里
    assert "看桌面有什么" not in req.user_content, f"原话被混入: {req.user_content!r}"

    # 不变式 ⑤：必须明确告诉 DS 这是工具回执
    assert "工具" in req.user_content, f"必须提到'工具': {req.user_content!r}"
    assert "111.txt" in req.user_content, f"工具结果必须包含原文: {req.user_content!r}"


def test_react_continuation_no_user_duplicate():
    """即使 body 里有多条 user message，react 续接也只取 tool 内容。"""
    body = {
        "messages": [
            {"role": "user", "content": "原话 A"},
            {"role": "tool", "tool_call_id": "c1", "content": "结果 A"},
            {"role": "user", "content": "原话 B"},
            {"role": "tool", "tool_call_id": "c2", "content": "结果 B"},
        ]
    }

    req = build_ds_input(body)
    assert "原话 A" not in req.user_content
    assert "原话 B" not in req.user_content
    assert "结果 A" in req.user_content
    assert "结果 B" in req.user_content


# ── 不变式 ⑥：tool_call_id 稳定 ───────────────────────


def test_tool_call_id_stable_in_response():
    """DS 给的 tool_call_id 不能随机换。"""
    async def run():
        events = [
            Event("content", "工具 Bash\ncommand=\"x\"\n工具结束\n"),
            Event("done", None),
        ]
        async def event_iter():
            for e in events:
                yield e

        sse_chunks = []
        async for sse in stream_events_to_openai(event_iter(), request_id="chatcmpl-test", model="deepseek-v4-flash", tools_schema=[]):
            sse_chunks.append(sse)

        chunks = parse_sse("".join(sse_chunks))
        # 过滤掉 [DONE] 哨兵
        real_chunks = [c for c in chunks if not c.get("_done")]
        tc_chunks = [c for c in real_chunks if c["choices"][0]["delta"].get("tool_calls")]
        # 所有 tool_call chunk 的 id 必须一致
        ids = [tc["id"] for c in tc_chunks for tc in c["choices"][0]["delta"]["tool_calls"] if "id" in tc]
        assert ids, "至少要有一个 id"
        assert len(set(ids)) == 1, f"tool_call_id 必须稳定: {ids}"

    asyncio.run(run())


# ── 不变式 ①（变种）：housekeeping 拦截 ───────────────


def test_housekeeping_via_gateway():
    """housekeeping 请求（empty clean_prompt）→ gateway.is_claude_housekeeping_request 返回 True。"""
    import gateway

    body = {
        "messages": [{"role": "user", "content": "<system-reminder>\n[SUGGESTION MODE: predict]\n</system-reminder>"}]
    }
    assert gateway.is_claude_housekeeping_request(body), "housekeeping 必须被识别"


# ── 跑全部 ──────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_streaming_with_tool_calls_empty_content,
        test_streaming_text_only_finish_stop,
        test_streaming_thinking_only_must_send_role,
        test_react_continuation_only_tool_results,
        test_react_continuation_no_user_duplicate,
        test_tool_call_id_stable_in_response,
        test_housekeeping_via_gateway,
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

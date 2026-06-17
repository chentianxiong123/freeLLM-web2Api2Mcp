"""Mock 测试服务 — 独立跑在 :8081，用 BashListProvider + core.chat_handler。

干啥的：无论发什么，固定返回 Bash(Get-ChildItem) 的 tool_call。
用来验证 Claude Code 能不能识别代理返回的 tool_calls 并真正执行。

复用 v2 架构的 stream_chat_to_sse — 协议逻辑只有一份，不会漂。
"""
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

from providers.mock import BashListProvider
from core.chat_handler import stream_chat_to_sse

app = FastAPI()
PROVIDER = BashListProvider()


def _log_request(body: dict):
    """打印 body 结构到控制台，方便手测时看清 Claude Code 真实发了什么。"""
    print("=" * 60, flush=True)
    print(f"[MOCK] 收到请求 stream={body.get('stream')} model={body.get('model')}", flush=True)
    for i, m in enumerate(body.get("messages", [])):
        role = m.get("role")
        c = m.get("content")
        tcs = m.get("tool_calls")
        tcid = m.get("tool_call_id")
        if role == "tool":
            print(f"  [{i}] role=tool tool_call_id={tcid} content={str(c)[:100]!r}", flush=True)
        elif tcs:
            for tc in tcs:
                fn = tc.get("function", {})
                print(f"  [{i}] role=assistant tool_call name={fn.get('name')} args={fn.get('arguments','')[:100]}", flush=True)
        else:
            print(f"  [{i}] role={role} content={str(c)[:100]!r}", flush=True)
    tools = body.get("tools", [])
    print(f"[MOCK] tools: {[t.get('function',{}).get('name') for t in tools]}", flush=True)
    print("=" * 60, flush=True)


@app.post("/v1/chat/completions")
async def chat(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid json"})

    _log_request(body)
    is_stream = bool(body.get("stream", True))

    if is_stream:
        async def gen():
            async for sse in stream_chat_to_sse(PROVIDER, body):
                yield sse
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
    else:
        # 非流式：收集 SSE → 拼成 JSON
        full_content = ""
        tool_calls = []
        finish_reason = "stop"
        async for sse in stream_chat_to_sse(PROVIDER, body):
            line = sse.strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            try:
                chunk = json.loads(line[6:])
            except Exception:
                continue
            delta = chunk.get("choices", [{}])[0].get("delta", {})
            if "content" in delta and delta["content"]:
                full_content += delta["content"]
            if "tool_calls" in delta:
                for tc in delta["tool_calls"]:
                    if "id" in tc:
                        tool_calls.append({"id": tc["id"], "type": "function", "function": tc.get("function", {})})
            if chunk.get("choices", [{}])[0].get("finish_reason"):
                finish_reason = chunk["choices"][0]["finish_reason"]

        message = {"role": "assistant", "content": full_content or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return JSONResponse(content={
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model", "mock-model"),
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })


@app.get("/health")
async def health():
    return {"ok": True, "service": "mock", "provider": type(PROVIDER).__name__}


if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("Mock 测试服务 — 端口 8081")
    print("Provider: BashListProvider（永远返 Bash(Get-ChildItem)）")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8081)

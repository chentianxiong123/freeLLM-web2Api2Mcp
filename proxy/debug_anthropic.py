"""调试：测试重写后的 anthropic_handler"""
import config
import deepseek_api as ds_api
from anthropic_handler import convert_messages, CHINESE_TOOL_DEFS

cfg = config.load_config()

# 模拟 Claude Code 请求
messages = [{"role": "user", "content": "你好"}]

ds_messages = convert_messages(messages)
print("=== 转换后的消息 ===")
for m in ds_messages:
    print(f"  {m['role']}: {m['content'][:100]}")

print()
print("=== 工具定义 ===")
print(CHINESE_TOOL_DEFS[:200])

# 构建 prompt
prompt = CHINESE_TOOL_DEFS + "\n\n用户：你好"
print(f"\n=== 完整 prompt ({len(prompt)} chars) ===")
print(prompt[:300])

# 发给 DeepSeek
print("\n=== 发送测试 ===")
stream = ds_api.chat_completion(
    cfg=cfg,
    messages=[{"role": "user", "content": prompt}],
    model="deepseek-default",
    thinking_enabled=False,
    search_enabled=False,
    stream=True,
)

content_parts = []
for etype, val in stream:
    if etype == "content":
        content_parts.append(val)
        print(f"  [内容] {val}", flush=True)
    elif etype == "thinking":
        print(f"  [思考] {val[:60]}", flush=True)
    elif etype == "error":
        print(f"  [错误] {val}")
    elif etype == "done":
        print("  [完成]")
        break

full = "".join(content_parts)
print(f"\n=== 完整响应 ({len(full)} chars) ===")
print(full[:500])

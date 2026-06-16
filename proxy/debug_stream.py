"""调试：查看 DeepSeek 原始流响应"""
import config
import deepseek_api as ds

cfg = config.load_config()

stream = ds.chat_completion(
    cfg=cfg,
    messages=[{"role": "user", "content": "你好"}],
    model="deepseek-default",
    thinking_enabled=False,
    search_enabled=False,
    stream=True,
)

content_parts = []
for etype, val in stream:
    print(f"  [流事件] type={etype}, val={str(val)[:100]}")
    if etype == "content":
        content_parts.append(val)
    elif etype == "done":
        break

full = "".join(content_parts)
print(f"\n完整内容: \"{full}\"")
print(f"内容长度: {len(full)}")

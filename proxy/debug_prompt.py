"""调试：逐步测试不同的 prompt 格式"""
import config, deepseek_api as ds
from anthropic_handler import CHINESE_TOOL_DEFS

cfg = config.load_config()

# 测试1：纯用户消息
print("=== 测试1: 纯用户消息 ===")
s = ds.chat_completion(cfg, [{"role":"user","content":"你好"}], "deepseek-default", False, False, stream=True)
for e in s:
    if e[0] == "content": print(f"  {e[1]}", end="", flush=True)
    elif e[0] == "done": print("\n  [OK]"); break
    elif e[0] == "error": print(f"\n  [ERR] {e[1]}")

# 测试2：工具定义 + 用户消息
print("\n=== 测试2: 工具定义 + 用户消息 ===")
prompt2 = CHINESE_TOOL_DEFS + "\n\n你好"
s = ds.chat_completion(cfg, [{"role":"user","content":prompt2}], "deepseek-default", False, False, stream=True)
for e in s:
    if e[0] == "content": print(f"  {e[1]}", end="", flush=True)
    elif e[0] == "done": print("\n  [OK]"); break
    elif e[0] == "error": print(f"\n  [ERR] {e[1]}")

# 测试3：工具定义 + 用户：你好
print("\n=== 测试3: 工具定义 + 用户：你好 ===")
prompt3 = CHINESE_TOOL_DEFS + "\n\n用户：你好"
s = ds.chat_completion(cfg, [{"role":"user","content":prompt3}], "deepseek-default", False, False, stream=True)
for e in s:
    if e[0] == "content": print(f"  {e[1]}", end="", flush=True)
    elif e[0] == "done": print("\n  [OK]"); break
    elif e[0] == "error": print(f"\n  [ERR] {e[1]}")

# 测试4：只工具定义
print("\n=== 测试4: 只工具定义 ===")
s = ds.chat_completion(cfg, [{"role":"user","content":CHINESE_TOOL_DEFS}], "deepseek-default", False, False, stream=True)
for e in s:
    if e[0] == "content": print(f"  {e[1]}", end="", flush=True)
    elif e[0] == "done": print("\n  [OK]"); break
    elif e[0] == "error": print(f"\n  [ERR] {e[1]}")

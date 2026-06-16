"""调试：查看 DeepSeek 原始流响应 - 详细"""
import config
import deepseek_api as ds

cfg = config.load_config()

# 测试不同的模型和参数
for model, thinking in [("deepseek-default", False), ("deepseek-reasoner", True)]:
    print(f"\n=== 测试 model={model}, thinking={thinking} ===")
    stream = ds.chat_completion(
        cfg=cfg,
        messages=[{"role": "user", "content": "回复一个字：好"}],
        model=model,
        thinking_enabled=thinking,
        search_enabled=False,
        stream=True,
    )

    has_any = False
    for etype, val in stream:
        has_any = True
        if etype == "content":
            print(f"  [内容] {val}", end="", flush=True)
        elif etype == "thinking":
            print(f"  [思考] {val[:60]}...", flush=True)
        elif etype == "error":
            print(f"  [错误] {val}")
        elif etype == "done":
            print("  [完成]")
        else:
            print(f"  [未知] {etype}={str(val)[:80]}")
    if not has_any:
        print("  [无任何事件]")
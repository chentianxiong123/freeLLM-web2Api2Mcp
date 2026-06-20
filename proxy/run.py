# -*- coding: utf-8 -*-
r"""独立启动器 - 绕开 main.py 里的 spawn 链

用法:
    D:\uv\python\cpython-3.11-windows-x86_64-none\python.exe run.py
"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 关键：把 venv 的 site-packages 加进来（vstub launcher 自动做，
# 但用 uv 系统 python 直跑需要手动）
venv_site = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Lib", "site-packages")
if os.path.isdir(venv_site) and venv_site not in sys.path:
    sys.path.insert(0, venv_site)

# 关键：在 import 之前锁定 reload
os.environ.setdefault("DEEPSEEK_PROVIDER", "true")

import uvicorn

import config
import accounts

accounts.import_from_config()

cfg = config.load_config()
port = cfg.get("port", 48391)

print(f"=== DeepSeek Web Agent Proxy v0.3.0 (run.py) ===")
print(f"Listening on http://127.0.0.1:{port}")

# 显式禁用 reload/workers，避免 uvicorn spawn 子进程
import main
uvicorn.run(
    main.app,
    host="0.0.0.0",
    port=port,
    workers=1,
    reload=False,
    loop="asyncio",
    http="h11",
    log_config=None,
)

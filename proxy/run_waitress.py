"""用 waitress 启动 — 不会 spawn worker，单进程，Windows 友好"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("DEEPSEEK_PROVIDER", "true")

import main
import config
import accounts

accounts.import_from_config()
cfg = config.load_config()
port = cfg.get("port", 48391)

print(f"=== DeepSeek Web Agent Proxy v0.3.0 (waitress) ===")
print(f"Listening on http://0.0.0.0:{port}")

from waitress import serve
serve(main.app, host="0.0.0.0", port=port, threads=4)

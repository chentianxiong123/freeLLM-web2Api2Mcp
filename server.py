"""「外援老师」MCP server 入口（原创核心，tutor）。

运行方式:
    python server.py                          # stdio 传输(供 MCP 客户端直接连接)
    python server.py --http --port 8788       # HTTP 独立服务(Streamable HTTP)
"""

from __future__ import annotations

import argparse

from tutor.mcp import mcp, run_http


def main() -> None:
    parser = argparse.ArgumentParser(description="外援老师 MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="以 HTTP 传输运行(Streamable HTTP,供客户端连接 URL);不加则 stdio",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 监听地址")
    parser.add_argument("--port", type=int, default=8788, help="HTTP 监听端口")
    args = parser.parse_args()

    if args.http:
        run_http(args.host, args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

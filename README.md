# freeLLM-web2Api2Mcp

> **v3 主线：Web 搜索 MCP + 外援老师 MCP**（2026-11-08 起）。

## 版本状态

| 版本 | 形态 | 状态 |
|---|---|---|
| **v1** | DeepSeek/Qwen 网页端 → OpenAI API 代理 | 🪦 已归档（见 LEGACY.md） |
| **v2** | 同一项目改造为 MCP Server | 🪦 已归档 |
| **v3（当前）** | **原创「外援老师」核心 + 自建 Web 后台 + MCP 工具** | 🟢 当前主线 |

v1/v2 历史与贡献全部保留（63 commits，2 位贡献者），详见 [LEGACY.md](./LEGACY.md)。

## v3 是什么

把**国内网页版大模型**（豆包 / DeepSeek / Kimi / 通义千问 / 智谱清言 / 腾讯元宝）包装成
**MCP 工具**，供 coding agent 当「外援老师」调用——拿评审、教学、第二意见。

**联网搜索 = 提示词工程**：让模型自己搜，不接搜索 API、不抓正文。

## 技术栈

Python 3.10+ · Playwright（**复用本机 Chrome/Edge，零下载**）· FastAPI · mcp SDK。

> 核心层为**原创实现**（`tutor/`，MIT 许可），平台选择器配置为功能性事实数据
> （`tutor_platforms_data.json`，实测回填，来源见 LICENSE 说明）。

## 目录

```
tutor/                 原创核心层
├── config.py          平台配置 + 全局设置（浏览器/无头）
├── browser.py         系统浏览器复用 + 反指纹 + profile 会话锁
├── driver.py          Playwright 选择器驱动（提问/等回答/续聊/登录检测）
├── ask.py             调用编排（单平台 / auto / 登录检测 / 状态持久化）
├── mcp.py             MCP 工具（ask_web_llm / list_web_llms）
├── login.py           登录窗口启动
├── login_worker.py    登录工作进程（弹系统 Chrome）
└── lock.py            profile 会话锁
ui_server.py           自建 Web 后台（FastAPI）
server.py              MCP server 入口（stdio / HTTP）
tutor_platforms_data.json  平台配置数据（功能性事实）
```

## 部署

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
# 默认浏览器=系统 Chrome（复用本机，不下载）；改 data/settings.json 可切 msedge
./venv/bin/python ui_server.py --port 8787   # Web 后台 http://127.0.0.1:8787
./venv/bin/python server.py --http --port 8788   # MCP HTTP（Streamable HTTP）
./venv/bin/python server.py                      # MCP stdio
```

## 使用流程

1. 打开 Web 后台 `http://127.0.0.1:8787`
2. 对要用的平台点「🔑 登录」→ 弹系统 Chrome → 人工登录 → 关窗
3. 点「🔍 检测」确认已登录；「▶ 提问」测试（提示词让它搜东西）
4. MCP 接入：`ask_web_llm(platform="deepseek", prompt="...")` 或 `platform="auto"`

## CDP 真浏览器模式（风控最小）

```bash
./tools/start_cdp_browser.sh          # 复制真实profile + 删Singleton + 起9222
# UI 顶部「运行模式」→ 模式选 cdp + 地址 http://127.0.0.1:9222 + 保存
```

原理（Chrome 默认 profile 不能开远程调试，必须非默认 `--user-data-dir`）：
复制真实 profile（书签+历史+真实cookie）到专用目录，删 `Singleton*` 后以 `--user-data-dir`
启动 9222，CDP 连上即得**真指纹 + 真 cookie**（`navigator.webdriver=False`，检测站全过）。
已登录的平台直接可用，无需重新登录。

## 下一步（规划）

- [ ] 聚合层：并发调多平台 → 合并去重 → 按平台分组（只出摘要）
- [ ] Web 搜索开关：提示词工程（让模型自己联网搜）
- [ ] 生图（豆包 supports_image）

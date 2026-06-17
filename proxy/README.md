# DeepSeek Web Agent Proxy

把 DeepSeek 网页端免费对话转换为 OpenAI Chat Completions API，供 Claude Code（OpenAI 模式）作为后端模型使用。

## 特性

- **单会话持久化**：DeepSeek session 不重建，复用同一个聊天窗口
- **ReAct 工具调用**：支持 Claude Code 的工具循环（Bash / Read / Write / Edit 等）
- **自然语言协议**：DeepSeek 通过 `工具 名称 / key="value" / 工具结束` 输出工具调用，无需 function calling 协议
- **后台请求拦截**：自动识别并丢弃 Claude Code 的 housekeeping 请求（标题生成、建议模式等）
- **可配置规则引擎**：自定义拦截规则，运行时热更新

## 架构

```
main.py (FastAPI routes)
    └─→ core/chat_handler.py
            ├─→ core/react_loop.py        # 7 不变式 + DS 输入构造
            └─→ providers/
                 ├─→ base.py              # ChatProvider 协议
                 ├─→ mock.py              # BashListProvider / ScriptedProvider
                 └─→ deepseek.py          # DeepSeekProvider（真实 API 适配）
```

### 分层职责

| 层 | 职责 |
|----|------|
| `main.py` | 路由、JSON/SSE 包装、admin API |
| `core/chat_handler.py` | 编排：拦截 → 建输入 → 调 Provider → 转 SSE |
| `core/react_loop.py` | 7 条不变式 + `build_ds_input()` + `stream_events_to_openai()` |
| `providers/base.py` | `ChatProvider` 协议 + `Event` 数据类 |
| `providers/mock.py` | Mock provider，用于测试和开发 |
| `providers/deepseek.py` | 真实 DeepSeek API 适配 |
| `deepseek_api.py` | 底层：登录、PoW、SSE 解析、Token 刷新 |

## 启动

```bash
# 安装依赖
pip install fastapi uvicorn curl-cffi

# Mock 模式（默认，永远返回 Bash 工具调用）
python main.py

# 真实 API 模式
DEEPSEEK_PROVIDER=true python main.py

# 独立 mock 测试服务（端口 8081）
python mock_server.py
```

## 测试

```bash
# 7 条不变式 + Provider 语义 + 端到端集成
python tests/test_react.py
python tests/test_deepseek_provider.py
python tests/test_integration.py
```

## 端点

| 端点 | 说明 |
|------|------|
| `POST /v1/chat/completions` | OpenAI 兼容入口 |
| `GET /v1/models` | 列出可用模型 |
| `GET /health` | 健康检查 |
| `GET /admin` | 管理控制台（HTML） |
| `POST /api/tool-config/init` | 向 DeepSeek 注入工具模板（建立游戏语境） |
| `POST /api/sessions/new` | 创建新会话 |
| `POST /api/sessions/activate` | 切换活跃会话 |
| `GET/POST /api/rules*` | 拦截规则 CRUD |

## 配置

通过 `/login` 端点登录后，token / session_id 自动持久化到 `config.json`（已 gitignore）。

工具定义模板：编辑 `tool_config.json` 后调 `/api/tool-config/init` 推送给 DeepSeek。

## 协议说明

DeepSeek 不支持原生 function calling 协议，所以采用"自然语言暗语"方案：

```
好的，我先看看。

工具 Bash
command="Get-ChildItem -Force"
description="列出文件"
工具结束

工具 Read
file_path="C:/Users/a1/Desktop/111.txt"
offset="5"
limit="6"
工具结束

读取完毕。
```

`tool_format.py` 负责解析，转换过程：
1. 累积 DeepSeek 完整输出（不流式发送，避免污染）
2. 切出 `工具 ... 工具结束` 块
3. 按 `tools_schema` 推断参数类型（integer / number / boolean / string）
4. 残文本留作 content（但有工具块时 content 留空，遵守不变式 ②）
5. 转 OpenAI `tool_calls` delta 流，附 `finish_reason="tool_calls"`

## ReAct 续接不变式

测试用 7 条不变式钉死了所有边界（`tests/test_react.py`）：

1.  finish_reason 必发
2.  有 tool_call → content 留空（不污染 CC 看到的流）
3.  第一次流任何东西之前，role delta 必发
4.  react 续接时只发工具结果原文给 DS
5.  react 续接时必须明确告诉 DS "这是工具回执"
6.  tool_call_id 稳定传递
7.  finish_reason=tool_calls 时必须有 tool_calls delta

## License

MIT

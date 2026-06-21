# 重构计划 v1

## 目标
- **对外**：固定 OpenAI Chat Completions（下游可自行转 Anthropic 等）
- **上游**：可切换网页端 Backend（DeepSeek 先行，预留 Kimi/…）
- **下游**：Agent 适配器（工具参数形态、housekeeping、stream 策略、规则上下文）

## 目录
```
proxy/
  core/types.py          # TurnRequest, ProviderTurn
  agents/                # 下游适配
    base.py
    claude_code.py
    generic.py
    registry.py
  backends/              # 上游网页端
    base.py
    registry.py
    deepseek_web/        # provider + 绑定 deepseek_api
  pipeline/chat.py       # 编排：adapter → backend → handler 组装
  handler.py             # OpenAI 响应组装（collect_response）
  gateway.py             # prompt 清洗（可被 adapter 调用）
  main.py                # 路由 + 依赖注入
```

## 阶段
- [x] Phase 1：core + agents + backends registry + pipeline + main 接入
- [ ] Phase 2：admin 工具页 id/title 持久化 + 恢复默认
- [ ] Phase 3：第二个 backend 桩 + config `backend_id`
- [ ] Phase 4：agent 配置 JSON（每 agent 独立 rules/housekeeping 开关）

## 环境变量
- `WEB_BACKEND=deepseek`（默认）
- `DOWNSTREAM_AGENT=claude_code` | `generic` | 自动检测 header
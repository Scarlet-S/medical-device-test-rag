# Agent 工作台增强说明（v1.2）

## 目标

在不替换 RAGFlow 知识库与既有 204 道评测资产的前提下，将原有批量
脚本项目增强为可调用、可路由、可记忆、可评测和可观测的领域 Agent
服务。

## 运行链路

```text
Client / MCP Host
        |
      Nginx
        |
  FastAPI Agent API -------- Prometheus
        |       |
     RAGFlow   Redis
        |
法规 Agent / 测试设计 Agent / 评测 Agent
```

## 已实现能力

1. FastAPI 结构化问答、SSE 阶段事件和证据引用核查；
2. 法规、测试设计、评测三个专业 Agent；
3. 基于加权关键词、置信度和回退策略的可解释意图路由；
4. Redis TTL、消息上限与会话查询/删除；
5. 白名单题集异步评测任务、状态与结果 API；
6. Prometheus 指标、请求 ID 和不记录问答正文的 JSON 日志；
7. Nginx、FastAPI、Redis、Prometheus 的 Docker Compose 部署；
8. 基于 Streamable HTTP 的 MCP 工具服务。

## MCP 安全边界

- 知识问答、测试设计、引用核查和路由工具只调用固定内部 API；
- 评测工具仅允许 API 中登记的 baseline、holdout、expansion、practice、
  blind 五类题集，不能传入脚本路径或任意命令；
- API Key、Redis 密码和问答正文不进入结构化日志；
- MCP 服务仅在 Compose 内网暴露，由 Nginx 统一代理。

## 为什么暂不迁移到 OpenAI Agents SDK

当前生产链路使用 DeepSeek 生成模型、千问 Embedding/Rerank 和 RAGFlow
检索，现有 Agent 编排已经过项目题集验证。引入另一套模型 SDK 会增加
密钥、模型适配与评测变量，却不会自动改善检索或答案质量。因此 v1.2
保留 FastAPI/MCP 的开放边界；当后续明确采用支持 Responses API 的
OpenAI 模型，并需要 SDK 原生 handoff、guardrail 或 tracing 时，再将
现有六个 MCP 工具接入 Agents SDK。

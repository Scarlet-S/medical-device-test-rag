# Agent 评测与全链路追踪（v1.3）

## 目标

v1.3 在 v1.2 的三 Agent、Redis 记忆、异步评测、Prometheus、Nginx 和
MCP 基础上补齐两个工程闭环：一是用冻结题集证明路由与工具调用可测，
二是把一次请求从 FastAPI、Router、Agent、Tool 到 RAGFlow 的耗时和结果
串成可检索 Trace。

## 受控工作流

`POST /api/v1/agents/workflow` 依次执行：

1. 关键词加权意图路由，输出置信度和命中词；
2. 置信度低于 `0.55` 时追加领域检索约束，保留原问题；
3. 调用法规、测试设计或评测 Agent；
4. 对回答中的 `[ID:n]` 与本轮证据片段做确定性映射核验；
5. 有证据但引用缺失或无效时，最多进行一次引用格式修复重试；
6. 返回工具轨迹、完成状态、耗时及启发式 Token/费用估算。

该流程不进行无限自主循环，也不允许模型自行选择任意外部命令。重试次数
固定为 `0` 或 `1`，查询改写和重试均进入工具轨迹与监控指标。

## 冻结 Agent 评测集

`evaluation/agent/agent_evaluation_v1.json` 含 30 道题，法规、测试设计、
评测三类各 10 道。每题声明预期 Agent、必需工具、最低引用数，以及需要
时的查询改写预期。

统一输出指标：

- Router：Accuracy、Macro-F1、路由置信度；
- Tool：必需工具召回率、实际工具成功状态；
- Retrieval：最低证据覆盖率；
- Agent：任务完成率、各 Agent 成功数；
- Performance：端到端 p50/p95 延迟；
- Cost：启发式输入/输出 Token 与可选的美元费用估算。

费用只有在 `.env` 中配置以下单价后才会计算：

```dotenv
LLM_INPUT_COST_PER_1M_TOKENS=0
LLM_OUTPUT_COST_PER_1M_TOKENS=0
```

RAGFlow 当前响应没有返回供应商 usage，因此该数字明确标记为 heuristic，
不能表述为真实账单费用。

## OpenTelemetry 与 Jaeger

Compose 中的 API 和 MCP 服务使用 OTLP/HTTP 将 Trace 发送到 Jaeger：

```dotenv
OTEL_TRACES_ENABLED=true
OTEL_TRACE_SAMPLE_RATIO=1.0
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://jaeger:4318/v1/traces
```

启动后打开 `http://localhost:16686`，选择
`medical-device-agent-api` 服务。一次工作流应能看到 HTTP、路由工作流、
专业 Agent、RAGFlow 工具及证据重试等 Span。Trace 属性只记录 Agent、
工具、状态和文本长度，不记录问题正文、回答正文或密钥。

## Prometheus 查询示例

各 Agent 五分钟成功率：

```promql
sum by (agent) (rate(mdtr_agent_executions_total{status="success"}[5m]))
/
sum by (agent) (rate(mdtr_agent_executions_total[5m]))
```

各 Agent p95 延迟：

```promql
histogram_quantile(
  0.95,
  sum by (agent, le) (rate(mdtr_agent_duration_seconds_bucket[5m]))
)
```

各 Agent 启发式 Token 与费用累计值：

```promql
sum by (agent, direction) (mdtr_agent_estimated_tokens_total)
sum by (agent) (mdtr_agent_estimated_cost_usd_total)
```

## 验证顺序

```powershell
python -m pytest
docker compose -f deploy/docker-compose.agent.yml up -d --build
python scripts/run_agent_eval.py --limit 3 --label agent_v1_smoke
python scripts/run_agent_eval.py --limit 30 --label agent_v1_frozen
```

先保留首次冻结结果，再根据失败类型决定优化 Router、Prompt、切片或工具，
不得直接把测试题答案注入系统提示词。

## 冻结评测结果（2026-08-25）

首次30题运行成功14题、失败16题。失败请求均在约30秒返回502，且容器内
`RAGFLOW_CHAT_TIMEOUT_SECONDS=30`，因此该结果判定为基础设施超时，不能
据此评价Router质量。原始结果被保留，未覆盖或删除。

将RAGFlow单次问答超时调整为60秒后，只补测原16道失败题，16/16均返回
成功；其中存在超过30秒但少于60秒的正常响应，验证了根因判断。随后使用
`merge_agent_eval_retry.py`按`case_id`合并成功补测，最终结果为：

- API执行成功率：100%（30/30）；
- 端到端路由准确率：100%；
- 路由Macro-F1：100%；
- 必需工具召回率：100%；
- 最低证据覆盖率：100%；
- 任务完成率：96.7%（29/30）；
- p50延迟：27.5秒；
- p95延迟：56.2秒。

唯一未完成题为A026。该题正确路由至评测Agent并返回8条证据，但回答没有
生成可映射的内联引用，证据核验状态为`missing_inline_citations`。该问题
属于回答引用格式质量，不属于路由或检索失败，保留为下一轮优化样本。

评测脚本同时输出两组指标：成功响应上的条件质量指标，以及把传输失败计入
分母的端到端指标。这样即使服务发生超时，也不会再出现“仅14题成功但路由
准确率显示100%”而缺少可靠性说明的情况。

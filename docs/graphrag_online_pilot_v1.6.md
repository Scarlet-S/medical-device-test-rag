# GraphRAG 在线试运行 v1.6

## 目标与边界

v1.6 在不改变现有 `/api/v1/chat` 和 RAGFlow 问答链路的前提下，新增
`/api/v1/graphrag/search` 独立接口。只有显式调用该接口时才启用图检索；
当图中无法形成可解释路径时，可自动回退到原有 RAGFlow 问答。

这仍是小规模 GraphRAG-style 工程试运行，不是 Microsoft GraphRAG 的完整
生产部署，也没有引入 Neo4j 等外部图数据库。

## 真实切片索引

`scripts/build_graphrag_index.py` 通过现有 RAGFlow Dataset API 只读访问知识库：

- 读取 30 个文件条目；
- 读取 897 个已解析切片；
- 使用透明的领域别名规则识别 19 类实体；
- 建立 464 条带原始切片 ID 的可追溯关系（446 条共现关系、18 条受控语义关系）；
- 优先使用受控领域关系，实体共现关系仅作为兜底；
- 每条领域关系映射至真实 RAGFlow 切片，不调用 LLM 生成隐藏事实。

生成的 `ragflow_chunk_graph_v1.json` 包含原始切片正文，只保存在本地并由
`.gitignore` 排除，避免将受版权约束的标准内容提交到公开仓库。

## 在线接口

请求示例：

```json
{
  "question": "从威胁建模到剩余漏洞处置需要哪些证据环节？",
  "top_k": 4,
  "max_hops": 6,
  "fallback_to_ragflow": true
}
```

响应包含：检出的实体、节点路径、关系谓词、对应证据切片、置信度、运行模式
和回退原因。Prometheus 记录调用结果、耗时和路径跳数，OpenTelemetry 记录
`graphrag.search` Span。

## 冻结留出结果

开发验证集的首轮原始结果保留在本地，此后用于修复别名覆盖和路径选择逻辑，
因此不再作为最终泛化证明。修复完成后创建新的 10 题冻结留出集
`online_multihop_holdout_v2.json`，其 SHA-256 为：

`c126eb81f54b75ef6d8a23dfbcb22a87afbe94afb242e15085fb77c281d011f2`

该留出集只运行一次，未根据结果继续调整图谱或别名：

| 指标 | 普通词法证据检索 | GraphRAG 在线检索 |
|---|---:|---:|
| 平均实体证据召回 | 64.7% | 85.8% |
| 完整关系路径率 | 不适用 | 90.0%（9/10） |
| 明确改善题目 | — | OH002、OH003、OH007、OH008 |

唯一未完全符合预期路径的 OH006 选择了“缺陷→回归结果→回归范围”，而预期为
“缺陷→风险分析→回归范围”。系统仍返回相关证据，但说明同一终点存在多条合法
路径时还需要关系优先级或查询意图约束。本项目保留该失败案例，不继续针对留出题
调参。

## 复现

```powershell
python scripts/build_graphrag_index.py

python scripts/run_online_graphrag_eval.py `
  --cases evaluation\graphrag\online_multihop_holdout_v2.json `
  --output evaluation\results\graphrag_online_holdout_v2_once.json
```

运行 API 时，在 `.env` 中将 `GRAPHRAG_INDEX_PATH` 指向本地真实切片图索引。
如不配置，则使用仓库内不含受限原文的小型演示图谱。

## Docker 安全加载与部署验收

真实切片图索引含受版权约束的原始片段，因此同时由 `.gitignore` 和
`.dockerignore` 排除，不进入 Git 历史或 Docker 镜像。Compose 在运行时将
`evaluation/graphrag` 挂载到 `/app/evaluation/graphrag`，且挂载权限为只读。

PowerShell 部署命令：

```powershell
$env:GRAPHRAG_INDEX_PATH="evaluation/graphrag/ragflow_chunk_graph_v1.json"
docker compose --env-file .env -f deploy/docker-compose.agent.yml up -d --build
```

2026-08-27 的 v1.6.0 发布验收结果：

- 52 项单元测试全部通过；
- API、Redis 和 MCP 健康检查通过，Nginx、Prometheus、Jaeger 正常运行；
- 镜像内不存在真实切片图索引，API 容器可通过只读挂载加载该索引；
- `/health` 返回 `status=ok` 且 `ragflow_connected=true`；
- 真实多跳问题返回 `mode=graph`、置信度 0.97、4 跳路径和 4 条证据；
- `/metrics`、Prometheus Ready 和 Jaeger UI 均返回 HTTP 200；
- Jaeger 已记录 `medical-device-agent-api` 服务与 `graphrag.search` Span；
- MCP Streamable HTTP 连接成功并公开 7 个受控工具。

发布说明见 [v1.6.0 Release](release_v1.6.0.md)。

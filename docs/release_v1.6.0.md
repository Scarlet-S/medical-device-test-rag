# v1.6.0：真实切片 GraphRAG 在线试运行

v1.6.0 在保持原有 RAGFlow `/chat` 链路不变的前提下，增加可选的在线
GraphRAG-style 检索接口，并完成真实切片索引、可追溯证据路径、安全回退、
监控追踪和 Docker Compose 部署验收。

## 主要更新

- 新增 `/api/v1/graphrag/search`，返回实体、关系路径、真实切片证据、置信度、
  运行模式和回退原因。
- 从当前 RAGFlow 知识库的 30 个文件条目、897 个切片构建本地图索引，形成
  464 条可追溯关系。
- 优先使用受控领域语义关系，以切片共现关系兜底；图中无法形成可靠路径时
  自动回退到现有 RAGFlow 问答。
- 新增 GraphRAG Prometheus 指标和 `graphrag.search` OpenTelemetry Span。
- 真实索引不进入 Git 或 Docker 镜像，仅通过只读目录挂载在运行时加载。

## 冻结留出实验

- 问题数：10 道未用于后续调优的冻结多跳题；
- 普通词法检索平均实体证据召回：64.7%；
- GraphRAG 平均实体证据召回：85.8%；
- 完整预期路径率：90.0%（9/10）；
- 明确改善题目：OH002、OH003、OH007、OH008。

OH006 保留为失败案例：系统返回了相关证据，但选择的合法路径与冻结预期路径
不同，说明同一终点存在多条路径时仍需更强的关系优先级或查询意图约束。

## 部署验收

- 单元测试：52/52 通过；
- Docker Compose：API、Redis、MCP、Nginx、Prometheus、Jaeger 均成功启动；
- 健康检查：RAGFlow 连接正常；
- GraphRAG 冒烟请求：`mode=graph`，置信度 0.97，返回 4 跳路径和 4 条证据；
- 可观测性：Prometheus 指标可用，Jaeger 可检索 `graphrag.search` Span；
- MCP：连接成功，7 个领域工具可发现；
- 安全边界：镜像内不含真实切片索引，运行时挂载为只读。

## 使用方法

先生成本地真实切片索引：

```powershell
python scripts/build_graphrag_index.py
```

再启动完整服务栈：

```powershell
$env:GRAPHRAG_INDEX_PATH="evaluation/graphrag/ragflow_chunk_graph_v1.json"
docker compose --env-file .env -f deploy/docker-compose.agent.yml up -d --build
```

访问入口：

- API 文档：`http://localhost:8080/docs`
- Prometheus：`http://localhost:9090`
- Jaeger：`http://localhost:16686`
- MCP：`http://localhost:8080/mcp`

## 边界说明

该版本是面向简历项目和工程验证的小规模 GraphRAG-style 试运行，不是完整的
Microsoft GraphRAG 或生产级图数据库方案。知识库内容仍以监管机构最新正式文件
为准，本项目不构成医疗、法律或监管合规建议。

# Agent 与 GraphRAG 评测扩容（v1.7）

## 目标与真实性边界

v1.7 将原有 30 道 Agent 专项题和 10 道 GraphRAG 冻结多跳题扩展为
90 道与 40 道，并从两个实际 RAGFlow 知识库生成更大规模的可追溯图索引。
所有规模数字来自脚本输出或冻结文件，不通过复制题目、重复边或合成无来源
片段虚增。

## 90 道 Agent 专项冻结评测

`evaluation/agent/agent_evaluation_v2.json` 包含 90 道唯一问题，法规、测试设计、
回答评测三类各 30 道。除常规意图外，题集覆盖模糊问法、跨意图边界、低置信度
查询改写、引用编号异常、证据不足、概念混合、无依据期限和复合失败场景。

题集在首次在线运行前冻结，SHA-256 为：

`893b7416fea021be566c66ef54ea839aa357d72f18e9fe2c656bbe5dbc5fd9db`

冻结前的离线路由契约检查覆盖 90/90 道题。首次在线运行结果为：

- 一次运行成功：79/90（87.8%），11 道因 RAGFlow 502 或 70 秒客户端超时失败；
- 成功样本路由 Accuracy：100%；
- 成功样本路由 Macro-F1：100%；
- 成功样本必需工具召回率：100%；
- 成功样本引用覆盖率：100%；
- 成功样本任务完成率：96.2%；
- 成功样本 p95 延迟：52.7 秒。

项目保留该首轮结果，不把超时隐藏为业务失败。随后仅对 11 道基础设施失败题
进行同配置单题补测并生成独立合并视图：90/90 调用成功，端到端路由准确率、
Macro-F1、必需工具召回率与引用覆盖率均为 100%，任务完成率为 95.6%，p95
延迟为 51.4 秒。4 道未完成题分别由缺少内联引用或无效引用触发质量门禁，
属于 Agent 业务判定而非请求失败。

## 40 道 GraphRAG 冻结多跳评测

`online_multihop_holdout_v3.json` 包含 40 道唯一多跳问题，覆盖软件生命周期、
需求—设计—编码—测试追溯、配置发布、变更与现成软件、网络安全、可用性、
风险闭环和 FDA AI 医疗器械验证。每题预期路径至少包含两条关系边。

题集在首次运行前冻结，SHA-256 为：

`1d6663bbfdea545dbcab2d93fac4d172fb928257ba096bd50d6409f13da0bab0`

首次且唯一一次冻结运行结果：

- 普通词法检索平均实体证据召回率：63.5%；
- GraphRAG 平均实体证据召回率：79.0%；
- 明确改善：14/40 道；
- 严格完整预期路径率：45.0%（18/40）。

严格路径指标要求返回节点序列与预先声明的预期路径完全相同。同一终点存在替代
合法路径时也会判为未完整命中，因此该指标比“是否形成任意相关路径”更严格。
项目保留这一结果，不根据冻结题继续修改题集或图谱。

## 真实 RAGFlow 图索引

索引通过 RAGFlow Dataset API 只读读取以下两个知识库：

- 医疗器械控制软件测试知识库：30 个文件、897 个切片；
- FDA AI 医疗器械验证案例库：从 300 个文件中按确定顺序读取 255 个文件、
  4,103 个切片，达到总量上限后停止。

最终索引包含：

- 5,000 个真实 RAGFlow 切片；
- 51 类可解释实体；
- 1,578 条带证据切片 ID 的可追溯关系；
- 60 条受控语义关系，其余为基于实体别名共现生成的证据关系。

为防止高频实体对通过重复共现虚增关系数，同一实体对最多保留 8 条不同证据。
真实索引包含源片段正文，保存在本地并由 Git 忽略；公开仓库只提交模式、冻结
题集、生成脚本和校验文件。`evaluation/graphrag/index_manifest_v2.json` 记录
不含原文的来源计数、关系策略和本地索引 SHA-256，供审阅者核对规模指标。

## 复现

```powershell
python scripts/create_agent_evaluation_v2.py
python scripts/create_graphrag_v2_assets.py

python scripts/build_graphrag_index.py `
  --dataset-name "医疗器械控制软件测试知识库" `
  --dataset-name "FDA AI 医疗器械验证案例库" `
  --schema evaluation\graphrag\medical_device_graph_v2.json `
  --output evaluation\graphrag\ragflow_chunk_graph_v2.json `
  --max-total-chunks 5000 `
  --max-evidence-per-pair 8

python scripts/run_online_graphrag_eval.py `
  --index evaluation\graphrag\ragflow_chunk_graph_v2.json `
  --cases evaluation\graphrag\online_multihop_holdout_v3.json `
  --output evaluation\results\graphrag_online_holdout_v3_once.json `
  --top-k 8 --max-hops 8
```

## 已知限制

- 这是面向领域工程验证的 GraphRAG-style 本地图索引，不等同于完整 Microsoft
  GraphRAG 或生产级图数据库部署。
- 实体和关系由透明别名规则、真实片段共现与受控领域关系构成，没有使用 LLM
  生成不可审计的隐藏事实。
- 40 道冻结题可用于更稳定的对照，但仍不能代表所有医疗器械问题类型。
- 5,000 个切片达到本次设定上限，不代表两个知识库的全部内容均已进入图索引。
- Agent 合并视图用于展示受控故障恢复后的覆盖能力；系统稳定性仍应以首次运行
  87.8% 的调用成功率为准，不能只报告补测后的 100%。

# Medical Device Software Testing RAG Workbench

基于 RAGFlow 构建的医疗器械控制软件测试知识库与检索增强问答工作台。项目围绕医疗器械软件注册审查、网络安全、生产质量管理和现场检查等公开资料，提供带来源引用的专业问答与可复现评测流程。

## 项目目标

- 建设医疗器械软件测试领域的结构化知识库。
- 对官方 PDF、Markdown 文档进行解析、切片、向量化和混合检索。
- 通过 Rerank 与领域提示词生成可核查、带引用的回答。
- 建立人工基线、批量检索评测和 LLM 自动裁判流程。
- 量化 Top-1、Top-3、引用正确率、回答准确度和幻觉率。

## 主要功能

- 医疗器械软件测试文档知识库
- PDF 与 Markdown 文档解析和知识切片
- 向量检索与全文关键词混合检索
- Rerank 检索结果重排序
- 带来源编号和原文片段的 RAG 问答
- 50 道领域问题组成的人工基线题集
- RAGFlow API 批量问答与引用采集
- 严格文档命中与可接受等价文档命中评估
- 基于实际引用证据的 LLM 自动裁判
- 自动结果与人工基线对比及争议题复核

## 技术方案

- RAGFlow v0.26.4
- Docker Desktop、Docker Compose、WSL 2、Ubuntu
- Elasticsearch、MySQL、Redis、MinIO
- Python 3.14
- Requests、python-dotenv、openpyxl
- 混合检索：向量权重 0.50、全文权重 0.50
- Rerank：qwen3-rerank
- LLM API 与独立评测裁判助手
- Git / GitHub

## 评测设计

评测集包含 50 道人工整理的问题，每道题记录：

- 预期文档和章节定位
- 人工标准答案要点
- 实际回答与引用片段
- Top-1、Top-3 文档命中
- 引用正确性
- 回答准确度（0—2）
- 是否出现幻觉

为避免多轮上下文干扰，批量评测时每道题使用独立会话。自动裁判只接收用户问题、人工标准答案、待评测回答和回答实际引用的证据，不连接知识库，也不使用外部知识补充判断。

## 当前评测结果

最终配置批次：`batch_eval_50_vector50_fulltext50_20260725_150147`

| 指标 | 结果 |
|---|---:|
| 批量调用成功率 | 100%（50/50） |
| 严格检索 Top-1 | 78%（39/50） |
| 严格检索 Top-3 | 100%（50/50） |
| 可接受文档 Top-1 | 88%（44/50） |
| 可接受文档 Top-3 | 100%（50/50） |
| 人工复核引用正确率 | 100%（50/50） |
| 人工复核回答准确度 | 97%（97/100） |
| 人工复核幻觉率 | 4%（2/50） |
| 自动裁判与人工复核一致率 | 94%（47/50） |

严格文档命中率较低的主要原因是 DOC003 与 DOC004 存在大量语义相同的对应条款。项目同时保留严格来源指标和可接受等价来源指标，避免将内容正确但来源顺序不同的回答误判为失败。

权重对比实验测试了 `0.30/0.70`、`0.50/0.50` 和 `0.70/0.30` 三组向量/全文权重。最终选择 `0.50/0.50`：相比原基线，严格 Top-1 从 70% 提升到 78%，严格 Top-3 从 96% 提升到 100%，同时取得最高的可接受 Top-1。完整实验记录见 `evaluation/reviews/retrieval_parameter_experiment_20260725.md`。

## 系统展示

### Docker运行环境

![Docker容器运行状态](docs/screenshots/01-docker-containers.png)

### 知识库建设

![医疗器械软件测试知识库文档](docs/screenshots/02-knowledge-base-documents.png)

### 最终检索配置

![最终检索参数配置](docs/screenshots/03-final-retrieval-settings.png)

### 检索与引用问答

![知识库检索测试](docs/screenshots/04-retrieval-test.png)

![带来源引用的专业问答](docs/screenshots/05-chat-answer-with-citations.png)

### 评测结果

![50题批量检索评测](docs/screenshots/06-batch-evaluation.png)

![检索参数对比实验](docs/screenshots/07-parameter-comparison.png)

## 快速使用

创建 `.env` 并参考 `.env.example` 填写本地 RAGFlow 地址、API Key、问答助手名称和裁判助手名称。真实 `.env` 不应提交到 Git。

验证 RAGFlow API 连接：

```powershell
python scripts/check_connection.py
```

运行 50 道批量问答：

```powershell
python scripts/run_batch_eval.py --limit 50
```

计算检索和引用命中：

```powershell
python scripts/score_acceptable_hits.py
python scripts/score_citation_hits.py
```

运行 50 道自动裁判：

```powershell
python scripts/run_judge_eval.py --limit 50
```

比较自动裁判与人工基线：

```powershell
python scripts/compare_judge_baseline.py
```

比较两个检索参数实验：

```powershell
python scripts/compare_retrieval_experiments.py --baseline "基线JSON" --candidate "候选JSON"
```

生成的 JSON 和 CSV 保存在 `evaluation/results`，该目录中的运行结果默认不提交到 Git。

## 项目结构

```text
medical-device-test-rag/
├── evaluation/
│   ├── baseline/        # 人工评测工作簿
│   ├── config/          # 可接受等价文档配置
│   ├── reviews/         # 争议题人工复核记录
│   └── results/         # 本地批量运行结果
├── scripts/
│   ├── check_connection.py
│   ├── ragflow_client.py
│   ├── run_batch_eval.py
│   ├── score_acceptable_hits.py
│   ├── score_citation_hits.py
│   ├── test_judge.py
│   ├── run_judge_eval.py
│   ├── compare_judge_baseline.py
│   └── compare_retrieval_experiments.py
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## 当前进度

- [x] 安装并配置 WSL 2、Ubuntu、Git 和 Docker Desktop
- [x] 部署并验证 RAGFlow v0.26.4
- [x] 配置聊天、Embedding 和 Rerank 模型
- [x] 收集、分类并解析医疗器械软件官方公开资料
- [x] 创建领域知识库和问答助手
- [x] 建立 50 道人工基线评测题集
- [x] 编写 RAGFlow API 客户端和批量评测脚本
- [x] 实现严格命中、等价文档命中和引用命中评估
- [x] 创建并校准 LLM 自动裁判
- [x] 完成自动裁判与人工基线对比及争议题复核
- [x] 完成检索参数对比实验并确定最终权重
- [x] 整理系统截图和典型问答案例
- [x] 完善部署说明、演示材料

## 许可与资料声明

本仓库中的原创代码、评测脚本、配置示例和项目文档采用 [MIT License](LICENSE) 发布。

RAGFlow及其他第三方软件、模型和依赖仍遵循各自的上游许可证，本仓库不对其版权或商标作出重新授权。

项目使用的医疗器械监管资料来自公开渠道，资料目录与来源记录见 `data/catalog/document_catalog.csv`。相关原始文件的版权、解释权和更新权归各发布机构所有，本仓库不对监管原文进行重新授权。

本项目仅用于技术研究、软件测试知识管理和RAG效果评估，不构成医疗、法律或监管合规建议。实际使用时应以监管机构发布的最新正式文件为准。
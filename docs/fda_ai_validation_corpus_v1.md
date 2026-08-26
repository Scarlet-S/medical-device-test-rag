# FDA AI 医疗器械验证案例语料包 v1

## 定位

本语料包用于补充医疗器械软件测试知识库的真实产品验证案例，来源为
FDA AI-enabled Medical Devices 清单所关联的公开 510(k) 决定摘要。它属于
`real_world_validation_evidence` 知识层，适合检索产品用途、谓词器械对比、
性能验证、临床评价、网络安全和软件变更等案例。

该语料包不是法规或共识标准，不替代 NMPA、YY/T、GB/T 等中国监管与标准
资料。回答涉及适用要求时，必须区分中国监管要求、美国监管背景和产品案例。

## 可复现来源与选择规则

- 清单页：<https://www.fda.gov/medical-devices/software-medical-device-samd/artificial-intelligence-enabled-medical-devices>
- 官方 CSV：<https://www.fda.gov/media/178541/download?attachment>
- 510(k) PDF：`https://www.accessdata.fda.gov/cdrh_docs/pdfYY/Kxxxxxx.pdf`
- 清单快照：1,524 条，其中 1,466 条具有可匹配的 510(k) 编号。
- 选择方式：按最终决定日期倒序，确定性选择 300 份；Radiology 最多保留
  120 份，降低单一专业面板对语料的支配。
- 时间范围：2023-03-17 至 2026-03-30。
- 源文件规模：300 份 PDF，共 493,172,738 字节，下载失败 0 份。

选择结果覆盖 15 个专业面板：Radiology 120、Cardiovascular 69、Neurology
47、Gastroenterology-Urology 19、Anesthesiology 14、Orthopedic 7、
Hematology 6，其余 18 份分布于 General and Plastic Surgery、Pathology、
Ophthalmic、General Hospital、Microbiology、Obstetrics and Gynecology、
Dental 和 Clinical Chemistry。

## 批量处理流程

```text
FDA 官方 CSV
  -> 510(k) 编号筛选与专业面板限额
  -> 并发下载并校验 PDF 签名
  -> SHA-256 去重与来源目录
  -> Docling 结构化转录
  -> LangChain 标题/递归切片
  -> FDA 模板噪声、乱码和低信息片段过滤
  -> SQLite 状态与断点续跑
  -> JSONL、质量报告与 Prometheus 指标
  -> 人工确认后才允许 RAGFlow API 入库
```

准备语料：

```powershell
python scripts/prepare_fda_ai_validation_corpus.py `
  --limit 300 `
  --radiology-cap 120 `
  --workers 8
```

离线解析：

```powershell
python scripts/ingest_batch_documents.py `
  --manifest "config\document_ingestion_manifest.fda_ai_validation_v1.json" `
  --workers 2
```

仅调整清洗或切片规则时复用 Docling 转录：

```powershell
python scripts/ingest_batch_documents.py `
  --manifest "config\document_ingestion_manifest.fda_ai_validation_v1.json" `
  --workers 4 `
  --reuse-structured
```

## 离线验收结果

- 成功解析：300/300。
- 唯一源文件 SHA-256：300/300。
- 最终切片：17,482。
- 空切片：0；乱码切片：0；文档内精确重复：0。
- 已过滤源片段：7,307，其中 FDA 通用模板 2,987、乱码 25、仅标题或
  图片占位 1,241、低信息片段 3,054。
- 跨文档精确重复：541 条，占 3.09%。剩余内容包含处方使用类型、PCCP
  变更要求等可能具有检索价值的共同要求，因此不做无差别全局删除。
- 低信息审查候选：975 条，占 5.58%，主要是表格短字段和“Not applicable”
  等仍可能构成产品验证证据的内容。
- 切片长度：中位数 639，P95 为 883，最大 900。
- JSONL 格式错误：0；报告切片数不一致文档：0。
- 最初完整 Docling 解析耗时约 56.4 分钟；复用结构化转录后，300 份文档
  可在约 5 秒内重新执行清洗与切片。

机器可读目录见
[`data/catalog/fda_ai_validation_corpus_v1.csv`](../data/catalog/fda_ai_validation_corpus_v1.csv)，
摄取清单见
[`config/document_ingestion_manifest.fda_ai_validation_v1.json`](../config/document_ingestion_manifest.fda_ai_validation_v1.json)，
聚合质量摘要见
[`docs/fda_ai_validation_corpus_v1_quality.md`](fda_ai_validation_corpus_v1_quality.md)。

## 入库安全边界

当前阶段只完成下载、结构化解析、清洗、切片和离线质量验收，尚未把 300 份
文档写入活动 RAGFlow 知识库。正式入库前建议：

1. 新建独立数据集 `FDA AI 医疗器械验证案例库`，避免与中国规范层混合。
2. 使用 `scripts/create_smoke_ingestion_manifest.py` 生成覆盖专业面板的 20 份
   冻结清单，再执行 RAGFlow API 小批量入库并检查引用和语言路由。
3. 建立未参与切片优化的案例检索题集，确认 Top-3、引用正确率和回答边界。
4. 评估 Embedding API 的额度和成本，再批准完整 300 份入库。

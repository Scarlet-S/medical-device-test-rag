# 实践层评测集

本目录用于评估 `PRACTICE001` 至 `PRACTICE008` 八份项目原创工程实践文档。

## 题集定位

- 共24题，每份实践文档3题。
- 这是覆盖回归集，不是独立留出集。
- 题目评估工程实践建议的检索和回答效果，不用于证明监管合规。
- 中国法规或标准结论仍需优先引用官方资料层。

## 运行

先运行3题冒烟测试：

```powershell
python scripts/run_batch_eval.py `
  --limit 3 `
  --workbook "evaluation\practice\practice_documents_evaluation_v1.json" `
  --label practice_documents_v1_smoke
```

通过后运行全部24题：

```powershell
python scripts/run_batch_eval.py `
  --limit 24 `
  --workbook "evaluation\practice\practice_documents_evaluation_v1.json" `
  --label practice_documents_v1_full
```

再对完整检索结果运行LLM裁判，并人工复核低分或争议题。

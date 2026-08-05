# 最终盲测题集 v1

## 冻结规则

- 题集包含30道新问题，覆盖当前23个逻辑知识来源。
- 题集冻结后不得用于切片编辑、相关问题配置、提示词修改、模型选择或检索参数调整。
- 正式评测只运行一次；脚本内部的自动重试属于同一次运行。
- 首次运行的原始JSON和CSV必须完整保留，包括失败题。
- 不对失败题单独补测，不合并重试结果，不根据结果发布修复后指标。
- 结果仅表示冻结配置在本题集上的一次性泛化表现。

## 运行前检查

只允许执行连接检查，不得逐题进行检索测试：

```powershell
python scripts/check_connection.py
```

确认RAGFlow和模型服务可用后，执行唯一一次正式评测：

```powershell
python scripts/run_batch_eval.py `
  --limit 30 `
  --workbook "evaluation/blind/final_blind_evaluation_v1.json" `
  --label final_blind_v1_once
```

完成后不得立即运行自动裁判或修改系统。先保存终端输出、JSON和CSV文件名，再记录原始检索指标。

## 冻结配置

- 相似度阈值：0.20
- 向量/全文权重：0.50/0.50
- Top N：8
- Top-K：128
- Rerank：qwen3-rerank
- 跨语言搜索：关闭
- 聊天超时：30秒

## 完整性校验

正式题集文件的SHA-256记录在同目录的`SHA256SUMS.txt`中。运行前可校验文件未被修改。

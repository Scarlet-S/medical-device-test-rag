# Scripts

This directory contains the custom Python scripts developed for this project.

Planned scripts include:

- Document catalog generation
- Metadata cleaning and validation
- Duplicate document detection
- RAGFlow API batch evaluation
- Evaluation metric calculation
- Experiment result analysis

## Single-document ingestion

`ingest_single_document.py` uploads one document, starts parsing, waits for
indexing, and writes a local chunk-quality report. It prevents duplicate
uploads by default.

Example:

```powershell
python scripts/ingest_single_document.py `
  --file "data/source_documents/example.pdf"
```

Use a document-specific general parser for project-authored Markdown:

```powershell
python scripts/ingest_single_document.py `
  --file "data/practice_documents/example.md" `
  --chunk-method naive
```

For a previously uploaded or failed document, use the exact filename with
`--use-existing`; add `--retry-failed` only after reviewing the failure.

## Evaluation result merging

`merge_eval_retry.py` replaces failed or explicitly selected successful
retrieval records with targeted reruns. Use `--replace-successful` only when
the rerun intentionally supersedes a successful earlier answer.

`merge_judge_retry.py` performs the equivalent operation for LLM judge
results and recalculates citation, answer-accuracy, and hallucination metrics.
It only merges existing JSON files and does not call the RAGFlow or model API.

```powershell
python scripts/merge_judge_retry.py `
  --base "evaluation/results/judge_eval_100_base.json" `
  --retry "evaluation/results/judge_eval_5_retry.json" `
  --source-result "evaluation/results/batch_eval_100_final.json" `
  --label official_expansion_final
```

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

## Batch document ingestion

`ingest_batch_documents.py` implements an offline, resumable ingestion
pipeline for Markdown, text, PDF, and DOCX files. It combines SHA-256
fingerprints, a SQLite checkpoint, a bounded `ProcessPoolExecutor`, Docling,
LangChain header/recursive splitting, RAGFlow API indexing, and Prometheus
metrics.

For a large real-world validation corpus, first prepare a deterministic sample
from the FDA AI-enabled medical device catalog. The default run downloads 300
public 510(k) decision summaries, caps Radiology at 120 documents, validates
PDF signatures, and generates a per-document ingestion manifest with source
URLs and SHA-256 hashes:

```powershell
python scripts/prepare_fda_ai_validation_corpus.py `
  --limit 300 `
  --radiology-cap 120 `
  --workers 8
```

The source PDFs are local-only. Review the generated catalog and then pass
`config/document_ingestion_manifest.fda_ai_validation_v1.json` to the batch
ingestion command below. These decision summaries form a real-world validation
evidence layer; they are not normative substitutes for Chinese regulations or
consensus standards.

Before a full RAGFlow import, create a deterministic 20-document smoke
manifest. The selector cycles through the `panel` metadata groups before taking
a second document from any group, so the smoke set covers 15 professional
panels instead of only the dominant Radiology records:

```powershell
python scripts/create_smoke_ingestion_manifest.py `
  --source "config/document_ingestion_manifest.fda_ai_validation_v1.json" `
  --output "config/document_ingestion_manifest.fda_ai_validation_smoke20_v1.json" `
  --limit 20 `
  --group-field panel
```

Install the optional ingestion dependencies first:

```powershell
python -m pip install -r requirements-ingestion.txt
```

Run a local-only dry run before modifying RAGFlow:

```powershell
python scripts/ingest_batch_documents.py `
  --manifest "config/document_ingestion_manifest.json" `
  --workers 2
```

After reviewing generated quality reports, add `--apply`. The script never
deletes an existing RAGFlow document. See
`docs/batch_document_ingestion.md` for index modes and recovery rules.

Aggregate document-level reports and JSONL chunks after a dry run:

```powershell
python scripts/summarize_ingestion_quality.py `
  --input-dir "data/processed/fda_ai_validation_corpus_v1" `
  --json-output "data/processed/fda_ai_validation_corpus_v1_quality.json" `
  --markdown-output "docs/fda_ai_validation_corpus_v1_quality.md"
```

If Docling output is already present and only cleanup or split rules changed,
reuse the structured Markdown instead of parsing every PDF again:

```powershell
python scripts/ingest_batch_documents.py `
  --manifest "config/document_ingestion_manifest.fda_ai_validation_v1.json" `
  --workers 4 `
  --reuse-structured
```

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

## Agent routing and tool evaluation

`run_agent_eval.py` calls the controlled Agent workflow and evaluates routing,
required tools, reference coverage, task completion, p95 latency, and
heuristic token/cost usage against the frozen 30-case Agent set.

```powershell
python scripts/run_agent_eval.py --limit 3 --label agent_v1_smoke
python scripts/run_agent_eval.py --limit 30 --label agent_v1_frozen
```

Set `AGENT_EVAL_TIMEOUT_SECONDS` and `AGENT_EVAL_MAX_ATTEMPTS` to control
network timeout and retries. The default is one attempt, so failures do not
silently turn into long waits.

If a frozen run contains transport failures, preserve it, rerun only those
case IDs, and merge successful retries without overwriting the first result:

```powershell
python scripts/merge_agent_eval_retry.py `
  --base "evaluation/results/agent_eval_30_base.json" `
  --retry "evaluation/results/agent_eval_16_retry.json" `
  --label agent_v1_merged
```

The report separates conditional quality metrics (successful responses only)
from end-to-end metrics that count transport failures against the full set.

## Offline GraphRAG comparison

`run_graphrag_comparison.py` compares deterministic lexical retrieval with a
small entity-relation path retriever on frozen medical-device multi-hop cases.
It does not call RAGFlow or any model API, so it is suitable for local and CI
regression checks.

```powershell
python scripts/run_graphrag_comparison.py `
  --output-json evaluation/results/graphrag_local.json `
  --output-csv evaluation/results/graphrag_local.csv `
  --fail-on-no-multihop-improvement
```

The experiment is deliberately described as GraphRAG-style evidence
retrieval, not as a production Microsoft GraphRAG deployment. See
`docs/graphrag_comparison_v1.md` for the frozen results and limitations.

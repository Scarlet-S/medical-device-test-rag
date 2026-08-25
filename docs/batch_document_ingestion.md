# Batch document ingestion

The batch ingestion pipeline converts heterogeneous source files into
auditable Markdown and JSONL chunks before optionally writing them to
RAGFlow. It is deliberately separate from the online Agent API so that large
offline jobs cannot block chat traffic.

## Architecture

```text
Manifest discovery
  -> SHA-256 fingerprint and SQLite checkpoint
  -> bounded ProcessPool
  -> Markdown/Docling extraction
  -> LangChain header split + recursive Chinese split
  -> chunk quality audit and local artifacts
  -> bounded RAGFlow API upload/index workers
  -> Prometheus metrics
```

The pipeline never deletes or replaces an existing RAGFlow document. An
unchanged source is skipped using its SHA-256 and pipeline signature. A
changed source is parsed into a new local artifact, but a same-name remote
document blocks the write unless `--reuse-existing` is explicitly supplied.
This guard prevents an accidental overwrite of the production knowledge
base.

## Installation

Use the project virtual environment:

```powershell
python -m pip install -r requirements-ingestion.txt
```

Docling 2.59.0 or later supports Python 3.14. Its first PDF conversion can
download model artifacts and therefore takes longer than Markdown parsing.

## Manifest

Copy `config/document_ingestion_manifest.example.json` and enable only the
documents intended for the current batch. Explicit `documents` and recursive
`sources[].glob` discovery can be combined. Supported inputs are Markdown,
text, PDF, and DOCX.

Two RAGFlow index modes are available:

- `ragflow_native`: upload normalized Markdown and let RAGFlow perform final
  parsing and indexing. This is the safe default.
- `manual_chunks`: write the LangChain chunks through RAGFlow's chunk API.
  Use this only after a smoke test in a temporary dataset because it changes
  which component owns the final chunk boundaries.

## Safe dry run

The default mode does not contact RAGFlow. It creates structured Markdown,
`chunks.jsonl`, a quality report, a SQLite checkpoint, and Prometheus text
metrics under the ignored `data/processed/` directory.

```powershell
python scripts/ingest_batch_documents.py `
  --manifest "config/document_ingestion_manifest.json" `
  --workers 2
```

Review each `quality_report.json`, especially empty, duplicate, mojibake,
very-short, and very-long counts. Missing headings are a warning rather than
an automatic failure because some short notices legitimately have no nested
heading.

### Reproducible smoke validation

The repository includes `config/document_ingestion_manifest.smoke.json` for
a real-document dry run using two project-owned practice documents. It does
not contact RAGFlow or modify the production knowledge base.

```powershell
python scripts/ingest_batch_documents.py `
  --manifest "config/document_ingestion_manifest.smoke.json" `
  --workers 2 `
  --force
```

The verified 2026-08-25 run processed both documents successfully and
generated 17 chunks in total. The quality audit reported zero empty,
duplicate, mojibake, missing-heading, very-short, or very-long chunks. A
second run without `--force` loaded both documents from the SHA-256/SQLite
cache, demonstrating incremental rerun and checkpoint behavior.

## Apply to RAGFlow

Start with one or two non-production documents:

```powershell
python scripts/ingest_batch_documents.py `
  --manifest "config/document_ingestion_manifest.json" `
  --apply `
  --dataset-name "医疗器械控制软件测试知识库" `
  --workers 2 `
  --ragflow-workers 2 `
  --metrics-port 9108
```

During the run, Prometheus can scrape
`http://127.0.0.1:9108/metrics`. The final exposition file remains available
at `data/processed/ingestion/metrics.prom` after the process exits.

If a previous run uploaded a document and then stopped, rerun with
`--reuse-existing`. Do not use that flag when the source content has changed;
review and retire the old RAGFlow document first to avoid mixing versions.

## Resume and force modes

- Normal rerun: unchanged validated/indexed files load from SQLite cache.
- `--force`: regenerate local artifacts and rerun indexing checks.
- Failed documents remain recorded with their error and attempt count.
- SQLite uses WAL mode so state updates remain durable during long jobs.

The local state database and generated artifacts are intentionally ignored by
Git. Commit the manifest (without secrets) and a summarized quality report,
not the full generated corpus.

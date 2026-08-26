import hashlib
import json
from pathlib import Path

import pytest
import requests

from scripts.ingest_batch_documents import (
    DocumentSpec,
    IngestionStateStore,
    audit_local_chunks,
    configure_local_model_cache,
    load_manifest,
    parse_document_worker,
    parse_with_docling,
    pipeline_signature,
    sha256_file,
    ingest_result_to_ragflow,
)


pytest.importorskip("langchain_text_splitters")


def write_manifest(path: Path, source: Path):
    payload = {
        "schema_version": 1,
        "defaults": {
            "chunk_size": 180,
            "chunk_overlap": 20,
            "index_mode": "ragflow_native",
        },
        "documents": [
            {
                "document_code": "DOC900",
                "title": "批量摄取测试",
                "path": str(source),
                "parser": "markdown",
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_manifest_and_markdown_pipeline_preserve_metadata(tmp_path):
    source = tmp_path / "DOC900_test.md"
    source.write_text(
        "# 风险管理\n\n## 7.1 风险控制\n\n"
        + "风险控制措施应形成记录。" * 30,
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    write_manifest(manifest, source)
    _, specs = load_manifest(manifest)
    spec = specs[0]
    source_hash = sha256_file(source)
    result = parse_document_worker(
        {
            "spec": spec.__dict__,
            "source_sha256": source_hash,
            "pipeline_signature": pipeline_signature(spec),
            "output_root": str(tmp_path / "processed"),
        }
    )

    assert result["chunk_count"] > 1
    records = [
        json.loads(line)
        for line in Path(result["chunks_path"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert all(record["document_code"] == "DOC900" for record in records)
    assert any("7.1 风险控制" in record["breadcrumb"] for record in records)
    assert all("来源文档：DOC900" in record["retrieval_text"] for record in records)


def test_sqlite_checkpoint_updates_attempts(tmp_path):
    source = tmp_path / "DOC901.md"
    source.write_text("# Test\n\nContent", encoding="utf-8")
    spec = DocumentSpec(
        document_code="DOC901",
        path=str(source.resolve()),
        title="Test",
        parser="markdown",
        chunk_size=800,
        chunk_overlap=80,
        chunk_method="naive",
        index_mode="ragflow_native",
        metadata={},
    )
    store = IngestionStateStore(tmp_path / "state.sqlite3")
    try:
        digest = sha256_file(source)
        signature = pipeline_signature(spec)
        store.mark(
            spec,
            digest,
            signature,
            "parsing",
            increment_attempt=True,
        )
        store.mark(spec, digest, signature, "validated", chunk_count=3)
        state = store.get(spec.path)
    finally:
        store.close()

    assert state["attempts"] == 1
    assert state["status"] == "validated"
    assert state["chunk_count"] == 3


def test_sha256_changes_when_source_changes(tmp_path):
    source = tmp_path / "document.md"
    source.write_text("first", encoding="utf-8")
    first = sha256_file(source)
    source.write_text("second", encoding="utf-8")
    second = sha256_file(source)
    assert first != second
    assert second == hashlib.sha256(b"second").hexdigest()


def test_model_cache_is_kept_in_ignored_processed_directory(monkeypatch):
    for name in ("HF_HOME", "HF_HUB_CACHE", "TORCH_HOME"):
        monkeypatch.delenv(name, raising=False)
    cache_root = configure_local_model_cache()
    assert cache_root.name == ".cache"
    assert cache_root.parent.name == "processed"


def test_quality_audit_detects_duplicate_and_mojibake():
    content = "有效条款内容"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    chunks = [
        {
            "content": content,
            "content_sha256": digest,
            "breadcrumb": "第一章",
        },
        {
            "content": content,
            "content_sha256": digest,
            "breadcrumb": "第一章",
        },
        {
            "content": "锟斤拷",
            "content_sha256": "other",
            "breadcrumb": "",
        },
    ]
    quality = audit_local_chunks(chunks, chunk_size=800)
    assert quality["duplicate_chunk_count"] == 1
    assert quality["mojibake_chunk_count"] == 1
    assert quality["missing_heading_count"] == 1


def test_docling_converts_docx_structure_to_markdown(tmp_path):
    docx = pytest.importorskip("docx")
    pytest.importorskip("docling")

    source = tmp_path / "DOC902_structure.docx"
    document = docx.Document()
    document.add_heading("软件验证", level=1)
    document.add_paragraph("验证活动应形成可追溯记录。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "活动"
    table.cell(0, 1).text = "证据"
    table.cell(1, 0).text = "单元测试"
    table.cell(1, 1).text = "测试报告"
    document.save(source)

    markdown = parse_with_docling(source)

    assert "软件验证" in markdown
    assert "验证活动应形成可追溯记录" in markdown
    assert "单元测试" in markdown
    assert "测试报告" in markdown


def test_upload_disconnect_reconciles_existing_remote_document(
    monkeypatch, tmp_path
):
    source = tmp_path / "DOC903_structured.md"
    source.write_text("# 软件测试\n\n测试记录应可追溯。", encoding="utf-8")
    spec = DocumentSpec(
        document_code="DOC903",
        path=str(source),
        title="软件测试",
        parser="markdown",
        chunk_size=800,
        chunk_overlap=80,
        chunk_method="naive",
        index_mode="ragflow_native",
        metadata={},
    )

    class FakeClient:
        list_calls = 0

        def find_dataset(self, _name):
            return {"id": "dataset-1"}

        def list_documents(self, _dataset_id):
            self.list_calls += 1
            if self.list_calls == 1:
                return []
            return [
                {
                    "id": "document-1",
                    "name": source.name,
                    "run": "DONE",
                    "chunk_method": "naive",
                }
            ]

        def upload_document(self, *_args, **_kwargs):
            raise requests.ConnectionError("connection closed after upload")

        def list_all_chunks(self, _dataset_id, _document_id):
            return [{"id": "chunk-1", "content": "测试记录应可追溯。"}]

    monkeypatch.setattr(
        "scripts.ingest_single_document.RAGFlowIngestionClient", FakeClient
    )
    result = type(
        "ParseResultStub",
        (),
        {"structured_path": str(source), "chunks_path": str(source)},
    )()

    remote = ingest_result_to_ragflow(
        spec,
        result,
        dataset_name="测试知识库",
        reuse_existing=True,
        wait_seconds=30,
        poll_seconds=1,
    )

    assert remote["document_id"] == "document-1"
    assert remote["chunk_count"] == 1

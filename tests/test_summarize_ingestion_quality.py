import json
from pathlib import Path

from scripts.summarize_ingestion_quality import summarize


def write_document(root: Path, code: str, contents: list[str]) -> None:
    target = root / code
    target.mkdir(parents=True)
    chunks_path = target / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as handle:
        for index, content in enumerate(contents, start=1):
            handle.write(
                json.dumps(
                    {
                        "chunk_index": index,
                        "content": content,
                    }
                )
                + "\n"
            )
    report = {
        "document": {
            "document_code": code,
            "title": code,
        },
        "source_sha256": code.lower(),
        "quality": {
            "chunk_count": len(contents),
            "empty_chunk_count": 0,
            "very_short_chunk_count": 0,
            "very_long_chunk_count": 0,
            "duplicate_chunk_count": 0,
            "missing_heading_count": 0,
            "mojibake_chunk_count": 0,
        },
        "artifacts": {"chunks_path": str(chunks_path)},
    }
    (target / "quality_report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )


def test_summarize_counts_cross_document_duplicates(tmp_path: Path) -> None:
    repeated = "A sufficiently informative repeated validation paragraph."
    write_document(tmp_path, "DOC1", [repeated, "First unique content."])
    write_document(tmp_path, "DOC2", [repeated, "Second unique content."])

    summary = summarize(tmp_path)

    assert summary["document_count"] == 2
    assert summary["chunk_count"] == 4
    assert summary["cross_document_exact_duplicate_extra_count"] == 1
    assert summary["chunk_count_mismatch_document_count"] == 0

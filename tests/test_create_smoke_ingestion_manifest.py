from pathlib import Path

from scripts.create_smoke_ingestion_manifest import (
    build_smoke_manifest,
    select_round_robin,
)


def sample_document(code: str, panel: str) -> dict:
    return {
        "document_code": code,
        "path": f"data/incoming/{code}.pdf",
        "metadata": {"panel": panel},
    }


def test_select_round_robin_covers_groups_before_second_round():
    documents = [
        sample_document("A1", "A"),
        sample_document("A2", "A"),
        sample_document("B1", "B"),
        sample_document("C1", "C"),
    ]

    selected = select_round_robin(documents, limit=4, group_field="panel")

    assert [item["document_code"] for item in selected] == ["A1", "B1", "C1", "A2"]


def test_build_smoke_manifest_uses_isolated_outputs():
    source = {
        "schema_version": 1,
        "defaults": {"parser": "docling_text_pdf", "output_dir": "full"},
        "documents": [sample_document("A1", "A"), sample_document("B1", "B")],
    }

    result = build_smoke_manifest(
        source,
        Path.cwd() / "config" / "full.json",
        limit=2,
        group_field="panel",
    )

    assert result["selection"]["selected_count"] == 2
    assert result["defaults"]["output_dir"].endswith("fda_ai_validation_corpus_v1")
    assert result["defaults"]["state_db"].endswith("smoke20_v1_state.sqlite3")

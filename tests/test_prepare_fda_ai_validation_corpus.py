from pathlib import Path

from scripts.prepare_fda_ai_validation_corpus import (
    DeviceRecord,
    is_valid_pdf,
    prioritize_records,
)


def record(number: int, panel: str, date: str) -> DeviceRecord:
    return DeviceRecord(
        decision_date=date,
        submission_number=f"K25{number:04d}",
        device=f"Device {number}",
        company="Example",
        panel=panel,
        product_code="QIH",
    )


def test_pdf_url_uses_submission_year():
    item = record(1, "Radiology", "01/02/2026")
    assert item.pdf_url.endswith("/pdf25/K250001.pdf")


def test_radiology_cap_preserves_other_panels_and_defers_overflow():
    records = [
        record(1, "Radiology", "01/05/2026"),
        record(2, "Radiology", "01/04/2026"),
        record(3, "Cardiovascular", "01/03/2026"),
        record(4, "Radiology", "01/02/2026"),
        record(5, "Neurology", "01/01/2026"),
    ]
    selected = prioritize_records(records, radiology_cap=2)
    assert [item.submission_number for item in selected] == [
        "K250001",
        "K250002",
        "K250003",
        "K250005",
        "K250004",
    ]


def test_pdf_validation_checks_signature_and_minimum_length(tmp_path: Path):
    valid = tmp_path / "valid.pdf"
    valid.write_bytes(b"%PDF-" + b"x" * 10_000)
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"<html>" + b"x" * 10_000)
    assert is_valid_pdf(valid)
    assert not is_valid_pdf(invalid)

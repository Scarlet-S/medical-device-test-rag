import json

from scripts.validate_repository_configs import discover_json_files, validate_json_files


def test_validator_reports_invalid_json_and_skips_results(tmp_path):
    valid = tmp_path / "config" / "valid.json"
    invalid = tmp_path / "evaluation" / "invalid.json"
    skipped = tmp_path / "evaluation" / "results" / "generated.json"
    valid.parent.mkdir(parents=True)
    invalid.parent.mkdir(parents=True)
    skipped.parent.mkdir(parents=True)
    valid.write_text(json.dumps({"ok": True}), encoding="utf-8")
    invalid.write_text("{", encoding="utf-8")
    skipped.write_text("{", encoding="utf-8")

    files = discover_json_files([tmp_path])
    errors = validate_json_files(files)

    assert valid in files
    assert invalid in files
    assert skipped not in files
    assert len(errors) == 1
    assert str(invalid) in errors[0]

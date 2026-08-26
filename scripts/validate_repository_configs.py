import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOTS = (PROJECT_ROOT / "config", PROJECT_ROOT / "evaluation")
SKIPPED_PARTS = {"results", "backups", ".pytest_cache", "__pycache__"}


def discover_json_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            if SKIPPED_PARTS.intersection(path.parts):
                continue
            files.append(path)
    return sorted(set(files))


def validate_json_files(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: {exc}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate tracked-style JSON configuration and evaluation files."
    )
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        help="Directories to scan. Defaults to config and evaluation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    roots = [path.resolve() for path in args.roots] or list(DEFAULT_ROOTS)
    files = discover_json_files(roots)
    errors = validate_json_files(files)
    print(f"Validated JSON files: {len(files)}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

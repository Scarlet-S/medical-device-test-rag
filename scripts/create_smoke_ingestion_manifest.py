"""Create a deterministic, stratified smoke manifest from a full corpus.

The generated manifest keeps document order within each metadata group and
selects one document per group in rounds.  It is intended to protect a large
RAGFlow corpus from accidental full ingestion during initial validation.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def select_round_robin(documents: list[dict], limit: int, group_field: str) -> list[dict]:
    if limit < 1:
        raise ValueError("limit必须大于0")
    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for document in documents:
        metadata = document.get("metadata") or {}
        group = str(metadata.get(group_field) or "Unknown").strip() or "Unknown"
        groups.setdefault(group, []).append(document)

    selected: list[dict] = []
    round_index = 0
    while len(selected) < min(limit, len(documents)):
        added = False
        for items in groups.values():
            if round_index < len(items):
                selected.append(copy.deepcopy(items[round_index]))
                added = True
                if len(selected) >= limit:
                    break
        if not added:
            break
        round_index += 1
    return selected


def build_smoke_manifest(
    source: dict,
    source_path: Path,
    limit: int,
    group_field: str,
) -> dict:
    documents = [
        document
        for document in source.get("documents", [])
        if document.get("enabled", True)
    ]
    if not documents:
        raise RuntimeError("源清单中没有启用的文档")
    selected = select_round_robin(documents, limit, group_field)
    defaults = copy.deepcopy(source.get("defaults") or {})
    defaults.update(
        {
            # Reuse the already-reviewed structured Markdown and JSONL files.
            # State and metrics stay isolated so the smoke run cannot mark the
            # full 300-document manifest as indexed.
            "output_dir": "data/processed/fda_ai_validation_corpus_v1",
            "state_db": "data/processed/fda_ai_validation_smoke20_v1_state.sqlite3",
            "metrics_output": (
                "data/processed/fda_ai_validation_smoke20_v1/metrics.prom"
            ),
        }
    )
    return {
        "schema_version": source.get("schema_version", 1),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection": {
            "kind": "metadata_round_robin",
            "group_field": group_field,
            "requested_limit": limit,
            "selected_count": len(selected),
            "source_manifest": source_path.relative_to(PROJECT_ROOT).as_posix(),
        },
        "defaults": defaults,
        "documents": selected,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从完整摄取清单生成确定性的分层小批量验收清单。"
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--group-field", default="panel")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_path = project_path(args.source)
    output_path = project_path(args.output)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    smoke = build_smoke_manifest(
        source,
        source_path,
        args.limit,
        args.group_field,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(smoke, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    group_counts: dict[str, int] = {}
    for document in smoke["documents"]:
        group = str((document.get("metadata") or {}).get(args.group_field) or "Unknown")
        group_counts[group] = group_counts.get(group, 0) + 1
    print(f"源文档：{len(source.get('documents', []))}")
    print(f"抽样文档：{len(smoke['documents'])}")
    print(f"分组覆盖：{len(group_counts)}")
    print(f"输出：{output_path}")
    for group, count in group_counts.items():
        print(f"- {group}: {count}")


if __name__ == "__main__":
    main()

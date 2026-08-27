"""Rebuild entity relations from a previously downloaded real-chunk index.

This avoids another RAGFlow API scan when only the entity schema or evidence
deduplication policy changes. The source chunks remain byte-for-byte text
records from the earlier read-only Dataset API export.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.graphrag import build_graph_dataset_from_chunks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-evidence-per-pair", type=int, default=8)
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    args = parse_args()
    source_path = resolve(args.source_index)
    schema_path = resolve(args.schema)
    output_path = resolve(args.output)
    source = json.loads(source_path.read_text(encoding="utf-8-sig"))
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    chunks = source.get("chunks", [])
    if not chunks:
        raise RuntimeError("源索引不包含真实切片")

    graph = build_graph_dataset_from_chunks(
        chunks,
        schema,
        name=str(source.get("name") or "ragflow-chunk-graph-v2"),
        max_evidence_per_pair=args.max_evidence_per_pair,
    )
    graph["generated_at"] = datetime.now(timezone.utc).isoformat()
    graph["source_datasets"] = source.get("source_datasets", [])
    graph["source_dataset"] = source.get("source_dataset", {})
    graph["relation_policy"] = {
        "method": "deterministic_alias_cooccurrence_with_curated_overlay",
        "max_evidence_per_pair": args.max_evidence_per_pair,
        "source_index": str(source_path.resolve()),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"真实切片数：{len(graph['chunks'])}")
    print(f"实体类型数：{len(graph['nodes'])}")
    print(f"可追溯关系数：{len(graph['relations'])}")
    print(f"输出：{output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

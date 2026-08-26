"""Compare lexical retrieval and online GraphRAG on frozen unseen queries."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.graphrag import GraphRAGIndex


DEFAULT_INDEX = (
    PROJECT_ROOT / "evaluation" / "graphrag" / "ragflow_chunk_graph_v1.json"
)
DEFAULT_CASES = (
    PROJECT_ROOT
    / "evaluation"
    / "graphrag"
    / "online_multihop_validation_v1.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "evaluation" / "results" / "graphrag_online_validation.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--max-hops", type=int, default=6)
    return parser.parse_args()


def entity_recall(evidence: list[dict], expected: list[str]) -> float:
    found = {
        entity for item in evidence for entity in item.get("entities", [])
    }
    return len(found.intersection(expected)) / len(expected)


def main() -> int:
    args = parse_args()
    index = GraphRAGIndex.from_path(args.index)
    cases = json.loads(args.cases.read_text(encoding="utf-8-sig"))["cases"]
    records = []
    for case in cases:
        baseline = index.lexical_evidence(case["question"], args.top_k)
        graph = index.search(case["question"], args.top_k, args.max_hops)
        expected = case["expected_nodes"]
        graph_nodes = graph.paths[0]["nodes"] if graph.paths else []
        baseline_recall = entity_recall(baseline, expected)
        graph_recall = entity_recall(graph.evidence, expected)
        records.append(
            {
                "case_id": case["case_id"],
                "type": case["type"],
                "question": case["question"],
                "expected_nodes": expected,
                "baseline_chunk_ids": [item["chunk_id"] for item in baseline],
                "graph_chunk_ids": [item["chunk_id"] for item in graph.evidence],
                "graph_path_nodes": graph_nodes,
                "baseline_entity_recall": round(baseline_recall, 4),
                "graph_entity_recall": round(graph_recall, 4),
                "graph_path_complete": int(graph_nodes == expected),
                "improved": int(graph_recall > baseline_recall),
            }
        )

    count = len(records)
    summary = {
        "case_count": count,
        "baseline_mean_entity_recall": round(
            sum(item["baseline_entity_recall"] for item in records) / count, 4
        ),
        "graph_mean_entity_recall": round(
            sum(item["graph_entity_recall"] for item in records) / count, 4
        ),
        "graph_complete_path_rate": round(
            sum(item["graph_path_complete"] for item in records) / count, 4
        ),
        "improved_case_ids": [
            item["case_id"] for item in records if item["improved"]
        ],
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "index": str(args.index.resolve()),
        "cases": str(args.cases.resolve()),
        "configuration": {"top_k": args.top_k, "max_hops": args.max_hops},
        "summary": summary,
        "results": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    csv_path = args.output.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        for item in records:
            row = dict(item)
            for key in (
                "expected_nodes",
                "baseline_chunk_ids",
                "graph_chunk_ids",
                "graph_path_nodes",
            ):
                row[key] = "|".join(row[key])
            writer.writerow(row)
    print("=" * 60)
    print(f"冻结问题数：{count}")
    print(
        "平均实体证据召回："
        f"{summary['baseline_mean_entity_recall']:.1%} -> "
        f"{summary['graph_mean_entity_recall']:.1%}"
    )
    print(f"完整证据路径率：{summary['graph_complete_path_rate']:.1%}")
    print(f"改善题目：{'、'.join(summary['improved_case_ids']) or '无'}")
    print(f"JSON结果：{args.output.resolve()}")
    print(f"CSV结果：{csv_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

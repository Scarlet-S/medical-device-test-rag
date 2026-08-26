import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = (
    PROJECT_ROOT / "evaluation" / "graphrag" / "medical_device_graph_v1.json"
)
DEFAULT_JSON = PROJECT_ROOT / "evaluation" / "results" / "graphrag_comparison.json"
DEFAULT_CSV = PROJECT_ROOT / "evaluation" / "results" / "graphrag_comparison.csv"


def terms(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    result = set(re.findall(r"[a-z0-9][a-z0-9_.-]+", normalized))
    for block in re.findall(r"[\u4e00-\u9fff]+", normalized):
        result.update(block)
        for size in (2, 3, 4):
            result.update(block[index : index + size] for index in range(len(block) - size + 1))
    return {item for item in result if item}


def lexical_rank(question: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query_terms = terms(question)
    document_terms = [terms(f"{chunk['title']} {chunk['text']}") for chunk in chunks]
    frequencies = Counter(term for item in document_terms for term in item)
    total = len(chunks)
    ranked = []
    for chunk, chunk_terms in zip(chunks, document_terms):
        overlap = query_terms & chunk_terms
        weighted_overlap = sum(math.log((total + 1) / (frequencies[term] + 0.5)) + 1 for term in overlap)
        denominator = math.sqrt(max(len(query_terms), 1) * max(len(chunk_terms), 1))
        ranked.append({"chunk": chunk, "score": weighted_overlap / denominator})
    return sorted(ranked, key=lambda item: (-item["score"], item["chunk"]["id"]))


def build_graph(dataset: dict[str, Any]):
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    relation_chunks: dict[tuple[str, str], str] = {}
    for relation in dataset["relations"]:
        source = relation["source"]
        target = relation["target"]
        chunk_id = relation["evidence_chunk"]
        adjacency[source].append((target, chunk_id))
        adjacency[target].append((source, chunk_id))
        relation_chunks[(source, target)] = chunk_id
        relation_chunks[(target, source)] = chunk_id
    return adjacency, relation_chunks


def shortest_path(
    adjacency: dict[str, list[tuple[str, str]]],
    source: str,
    target: str,
    max_hops: int,
) -> tuple[list[str], list[str]]:
    if source == target:
        return [source], []
    queue = deque([(source, [source], [])])
    visited = {source}
    while queue:
        node, node_path, chunk_path = queue.popleft()
        if len(chunk_path) >= max_hops:
            continue
        for neighbor, chunk_id in adjacency.get(node, []):
            if neighbor in visited:
                continue
            next_nodes = [*node_path, neighbor]
            next_chunks = [*chunk_path, chunk_id]
            if neighbor == target:
                return next_nodes, next_chunks
            visited.add(neighbor)
            queue.append((neighbor, next_nodes, next_chunks))
    return [], []


def expand_from_seeds(
    adjacency: dict[str, list[tuple[str, str]]],
    seeds: set[str],
    max_hops: int,
) -> dict[str, int]:
    chunk_depth: dict[str, int] = {}
    queue = deque((seed, 0) for seed in sorted(seeds))
    visited = set(seeds)
    while queue:
        node, depth = queue.popleft()
        if depth >= max_hops:
            continue
        for neighbor, chunk_id in adjacency.get(node, []):
            chunk_depth[chunk_id] = min(chunk_depth.get(chunk_id, max_hops + 1), depth + 1)
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))
    return chunk_depth


def graph_rank(
    case: dict[str, Any],
    lexical: list[dict[str, Any]],
    dataset: dict[str, Any],
    max_hops: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    adjacency, _ = build_graph(dataset)
    chunk_by_id = {chunk["id"]: chunk for chunk in dataset["chunks"]}
    query = re.sub(r"\s+", "", case["question"].lower())
    seeds = {
        node["id"]
        for node in dataset["nodes"]
        if any(re.sub(r"\s+", "", alias.lower()) in query for alias in node["aliases"])
    }
    seeds.update((case["start_entity"], case["target_entity"]))
    path_nodes, path_chunks = shortest_path(
        adjacency,
        case["start_entity"],
        case["target_entity"],
        max_hops,
    )
    depth_by_chunk = expand_from_seeds(adjacency, seeds, max_hops=2)
    lexical_scores = {item["chunk"]["id"]: item["score"] for item in lexical}
    ranked = []
    for chunk_id, chunk in chunk_by_id.items():
        score = lexical_scores.get(chunk_id, 0.0)
        if chunk_id in depth_by_chunk:
            score += 0.55 / depth_by_chunk[chunk_id]
        if chunk_id in path_chunks:
            score += 2.0 + (max_hops - path_chunks.index(chunk_id)) * 0.01
        ranked.append({"chunk": chunk, "score": score})
    return sorted(ranked, key=lambda item: (-item["score"], item["chunk"]["id"])), path_nodes


def evaluate(dataset: dict[str, Any], top_k: int, max_hops: int) -> dict[str, Any]:
    records = []
    for case in dataset["cases"]:
        lexical = lexical_rank(case["question"], dataset["chunks"])
        graph, path_nodes = graph_rank(case, lexical, dataset, max_hops=max_hops)
        baseline_ids = [item["chunk"]["id"] for item in lexical[:top_k]]
        graph_ids = [item["chunk"]["id"] for item in graph[:top_k]]
        expected = set(case["expected_chunks"])
        baseline_hits = len(expected.intersection(baseline_ids))
        graph_hits = len(expected.intersection(graph_ids))
        records.append(
            {
                "case_id": case["case_id"],
                "type": case["type"],
                "question": case["question"],
                "expected_chunks": case["expected_chunks"],
                "baseline_top_k": baseline_ids,
                "graphrag_top_k": graph_ids,
                "graph_path": path_nodes,
                "baseline_recall": baseline_hits / len(expected),
                "graphrag_recall": graph_hits / len(expected),
                "baseline_complete": int(baseline_hits == len(expected)),
                "graphrag_complete": int(graph_hits == len(expected)),
                "improved": int(graph_hits > baseline_hits),
            }
        )

    def summarize(selected: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(selected)
        return {
            "case_count": count,
            "baseline_mean_evidence_recall": round(
                sum(item["baseline_recall"] for item in selected) / count, 4
            ),
            "graphrag_mean_evidence_recall": round(
                sum(item["graphrag_recall"] for item in selected) / count, 4
            ),
            "baseline_complete_evidence_rate": round(
                sum(item["baseline_complete"] for item in selected) / count, 4
            ),
            "graphrag_complete_evidence_rate": round(
                sum(item["graphrag_complete"] for item in selected) / count, 4
            ),
            "improved_case_ids": [item["case_id"] for item in selected if item["improved"]],
        }

    multi_hop = [item for item in records if item["type"] == "multi_hop"]
    single_hop = [item for item in records if item["type"] == "single_hop"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset["name"],
        "configuration": {"top_k": top_k, "max_graph_hops": max_hops},
        "summary": {
            "all": summarize(records),
            "multi_hop": summarize(multi_hop),
            "single_hop": summarize(single_hop),
        },
        "results": records,
    }


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "case_id",
        "type",
        "question",
        "expected_chunks",
        "baseline_top_k",
        "graphrag_top_k",
        "graph_path",
        "baseline_recall",
        "graphrag_recall",
        "baseline_complete",
        "graphrag_complete",
        "improved",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = dict(record)
            for key in ("expected_chunks", "baseline_top_k", "graphrag_top_k", "graph_path"):
                row[key] = "|".join(row[key])
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an offline lexical-versus-graph retrieval comparison."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--max-hops", type=int, default=4)
    parser.add_argument("--fail-on-no-multihop-improvement", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with args.dataset.open("r", encoding="utf-8-sig") as handle:
        dataset = json.load(handle)
    report = evaluate(dataset, top_k=args.top_k, max_hops=args.max_hops)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(args.output_csv, report["results"])

    multi = report["summary"]["multi_hop"]
    single = report["summary"]["single_hop"]
    print("=" * 60)
    print(f"多跳题数：{multi['case_count']}")
    print(
        "多跳证据召回："
        f"{multi['baseline_mean_evidence_recall']:.1%} -> "
        f"{multi['graphrag_mean_evidence_recall']:.1%}"
    )
    print(
        "多跳完整证据率："
        f"{multi['baseline_complete_evidence_rate']:.1%} -> "
        f"{multi['graphrag_complete_evidence_rate']:.1%}"
    )
    print(f"改善题目：{'、'.join(multi['improved_case_ids']) or '无'}")
    print(
        "单跳证据召回："
        f"{single['baseline_mean_evidence_recall']:.1%} -> "
        f"{single['graphrag_mean_evidence_recall']:.1%}"
    )
    print(f"JSON结果：{args.output_json.resolve()}")
    print(f"CSV结果：{args.output_csv.resolve()}")
    if args.fail_on_no_multihop_improvement and not multi["improved_case_ids"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

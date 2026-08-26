import json
from pathlib import Path

from scripts.run_graphrag_comparison import evaluate, shortest_path, terms


DATASET = (
    Path(__file__).resolve().parents[1]
    / "evaluation"
    / "graphrag"
    / "medical_device_graph_v1.json"
)


def load_dataset():
    return json.loads(DATASET.read_text(encoding="utf-8"))


def test_chinese_terms_include_bigrams():
    assert "回归" in terms("回归测试范围")
    assert "回归测试" in terms("回归测试范围")


def test_shortest_path_returns_relation_evidence():
    dataset = load_dataset()
    adjacency = {}
    for relation in dataset["relations"]:
        adjacency.setdefault(relation["source"], []).append(
            (relation["target"], relation["evidence_chunk"])
        )
        adjacency.setdefault(relation["target"], []).append(
            (relation["source"], relation["evidence_chunk"])
        )
    nodes, chunks = shortest_path(adjacency, "software_update", "defect_record", 4)
    assert nodes == ["software_update", "regression_scope", "regression_result", "defect_record"]
    assert chunks == ["C005", "C006", "C007"]


def test_graphrag_improves_at_least_one_multihop_case_without_hurting_controls():
    report = evaluate(load_dataset(), top_k=4, max_hops=4)
    multi = report["summary"]["multi_hop"]
    single = report["summary"]["single_hop"]
    assert multi["graphrag_mean_evidence_recall"] > multi["baseline_mean_evidence_recall"]
    assert multi["improved_case_ids"]
    assert single["graphrag_mean_evidence_recall"] >= single["baseline_mean_evidence_recall"]

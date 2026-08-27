import hashlib
import json
from collections import Counter
from pathlib import Path

from app.agents.router import route_intent


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str) -> dict:
    return json.loads((PROJECT_ROOT / path).read_text(encoding="utf-8-sig"))


def test_agent_v2_dataset_is_balanced_and_matches_router_contract():
    dataset = load_json("evaluation/agent/agent_evaluation_v2.json")
    cases = dataset["cases"]

    assert len(cases) == 90
    assert len({item["case_id"] for item in cases}) == 90
    assert len({item["question"] for item in cases}) == 90
    assert Counter(item["expected_agent"] for item in cases) == {
        "regulatory": 30,
        "test_design": 30,
        "evaluation": 30,
    }
    for case in cases:
        route = route_intent(case["question"])
        assert route.selected_agent == case["expected_agent"]
        assert (route.confidence < 0.55) == case["expect_rewrite"]


def test_agent_v2_checksum_matches_frozen_dataset():
    path = PROJECT_ROOT / "evaluation/agent/agent_evaluation_v2.json"
    checksum_path = path.with_suffix(".sha256")
    expected = checksum_path.read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_graphrag_v2_schema_and_frozen_holdout_are_structurally_complete():
    schema = load_json("evaluation/graphrag/medical_device_graph_v2.json")
    holdout = load_json("evaluation/graphrag/online_multihop_holdout_v3.json")

    assert len(schema["nodes"]) == 51
    assert len(schema["relations"]) >= 60
    assert len(holdout["cases"]) == 40
    assert all(item["type"] == "multi_hop" for item in holdout["cases"])

    edges = {
        frozenset((item["source"], item["target"]))
        for item in schema["relations"]
    }
    for case in holdout["cases"]:
        expected_nodes = case["expected_nodes"]
        assert len(expected_nodes) >= 3
        assert all(
            frozenset((source, target)) in edges
            for source, target in zip(expected_nodes, expected_nodes[1:])
        )


def test_graphrag_v3_checksum_matches_frozen_holdout():
    path = PROJECT_ROOT / "evaluation/graphrag/online_multihop_holdout_v3.json"
    checksum_path = path.with_suffix(".sha256")
    expected = checksum_path.read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_graphrag_v2_public_manifest_records_target_scale():
    manifest = load_json("evaluation/graphrag/index_manifest_v2.json")

    assert manifest["real_chunk_count"] == 5000
    assert manifest["entity_type_count"] == 51
    assert manifest["traceable_relation_count"] == 1578
    assert (
        manifest["cooccurrence_relation_count"]
        + manifest["curated_relation_count"]
        == manifest["traceable_relation_count"]
    )
    assert sum(
        source["included_chunk_count"]
        for source in manifest["source_datasets"]
    ) == manifest["real_chunk_count"]

    local_index = (
        PROJECT_ROOT / "evaluation/graphrag/ragflow_chunk_graph_v2.json"
    )
    if local_index.exists():
        assert (
            hashlib.sha256(local_index.read_bytes()).hexdigest()
            == manifest["local_index_sha256"]
        )

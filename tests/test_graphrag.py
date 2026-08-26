from fastapi.testclient import TestClient

import app.main as api
from app.graphrag import (
    GraphRAGIndex,
    build_graph_dataset_from_chunks,
)


def test_graph_index_returns_complete_auditable_path():
    index = GraphRAGIndex.from_path()

    result = index.search(
        "从已识别的软件危险到最终形成可核查的测试证据，需要哪些环节？",
        top_k=4,
        max_hops=4,
    )

    assert result.paths[0]["hop_count"] == 4
    assert result.paths[0]["nodes"] == [
        "hazard",
        "risk_control",
        "safety_requirement",
        "design_code",
        "test_evidence",
    ]
    assert [item["chunk_id"] for item in result.evidence] == [
        "C001",
        "C002",
        "C003",
        "C004",
    ]
    assert result.confidence > 0.9


def test_build_graph_from_ragflow_chunks_keeps_source_evidence():
    schema = {
        "nodes": [
            {"id": "hazard", "label": "软件危险", "aliases": ["危险"]},
            {
                "id": "risk_control",
                "label": "风险控制措施",
                "aliases": ["风险控制措施"],
            },
        ]
    }
    chunks = [
        {
            "id": "real-chunk-1",
            "document_code": "DOC013",
            "document_name": "DOC013_standard.md",
            "content": "针对软件危险确定风险控制措施并保存证据。",
        }
    ]

    graph = build_graph_dataset_from_chunks(chunks, schema, "test-index")

    assert graph["chunks"][0]["id"] == "real-chunk-1"
    assert graph["chunks"][0]["document_name"] == "DOC013_standard.md"
    assert graph["relations"] == [
        {
            "source": "hazard",
            "predicate": "co_occurs_in_evidence",
            "target": "risk_control",
            "evidence_chunk": "real-chunk-1",
        }
    ]


def test_graphrag_api_returns_graph_path(monkeypatch):
    monkeypatch.setattr(api, "get_graphrag_index", GraphRAGIndex.from_path)
    client = TestClient(api.app)

    response = client.post(
        "/api/v1/graphrag/search",
        json={
            "question": "网络安全工作如何从威胁建模追踪到剩余漏洞处置？",
            "top_k": 3,
            "max_hops": 4,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "graph"
    assert payload["paths"][0]["hop_count"] == 3
    assert [item["chunk_id"] for item in payload["evidence"]] == [
        "C008",
        "C009",
        "C010",
    ]
    assert payload["answer"] == ""


def test_graphrag_api_falls_back_without_a_path(monkeypatch):
    class FakeRAGFlowClient:
        def ask(self, question):
            return {
                "question": question,
                "answer": "这是现有RAGFlow链路生成的回答。",
                "references": [
                    {
                        "document_name": "DOC001.pdf",
                        "content": "普通检索证据",
                        "similarity": 0.8,
                        "chunk_id": "fallback-1",
                    }
                ],
            }

    monkeypatch.setattr(api, "get_graphrag_index", GraphRAGIndex.from_path)
    monkeypatch.setattr(api, "get_ragflow_client", lambda: FakeRAGFlowClient())
    client = TestClient(api.app)

    response = client.post(
        "/api/v1/graphrag/search",
        json={"question": "请解释一个图谱中没有的新问题。"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "ragflow_fallback"
    assert payload["answer"].startswith("这是现有RAGFlow")
    assert payload["evidence"][0]["source"] == "ragflow"
    assert "安全回退" in payload["fallback_reason"]

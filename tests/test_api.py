import json
import logging

from fastapi.testclient import TestClient

import app.main as api
from app.agents.router import route_intent
from app.models import ConversationMessage, EvaluationJob
from app.observability import JsonFormatter


class FakeRAGFlowClient:
    chat = {"name": "测试知识助手"}
    chat_name = "测试知识助手"
    chat_id = "chat-test-001"

    def __init__(self):
        self.questions = []

    def ask(self, question: str):
        self.questions.append(question)
        return {
            "question": question,
            "answer": "软件安全性级别分为轻微、中等和严重三级。",
            "references": [
                {
                    "document_name": "DOC003_test.pdf",
                    "similarity": 0.91,
                    "content": "软件安全性级别分为轻微、中等和严重。",
                    "chunk_id": "chunk-001",
                    "positions": [[1, 1, 2, 3, 4]],
                }
            ],
            "session_id": "session-test-001",
            "chat_id": self.chat_id,
        }


class FakeMemoryStore:
    def __init__(self):
        self.conversations = {}

    async def ping(self):
        return True

    async def get_history(self, conversation_id):
        return list(self.conversations.get(conversation_id, []))

    async def append_exchange(
        self,
        conversation_id,
        user_message,
        assistant_message,
    ):
        messages = self.conversations.setdefault(conversation_id, [])
        created_at = "2026-08-25T00:00:00+00:00"
        messages.extend(
            [
                ConversationMessage(
                    role="user",
                    content=user_message,
                    created_at=created_at,
                ),
                ConversationMessage(
                    role="assistant",
                    content=assistant_message,
                    created_at=created_at,
                ),
            ]
        )

    async def delete(self, conversation_id):
        return self.conversations.pop(conversation_id, None) is not None


class FakeEvaluationManager:
    def __init__(self):
        self.jobs = {}

    async def start(self, request):
        job = EvaluationJob(
            job_id="eval-test-001",
            status="queued",
            request=request,
            created_at="2026-08-25T00:00:00+00:00",
        )
        self.jobs[job.job_id] = job
        return job

    async def get(self, job_id):
        return self.jobs.get(job_id)

    async def load_result(self, job):
        return {
            "summary": {"total": 1, "successful": 1},
            "results": [{"question_id": "Q001"}],
        }


def install_fake_client(monkeypatch):
    fake = FakeRAGFlowClient()
    monkeypatch.setattr(api, "get_ragflow_client", lambda: fake)
    return fake


def test_health_reports_connected_chat(monkeypatch):
    fake = install_fake_client(monkeypatch)
    client = TestClient(api.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "ragflow_connected": True,
        "chat_name": fake.chat_name,
        "chat_id": fake.chat_id,
    }


def test_ask_returns_structured_answer_and_references(monkeypatch):
    install_fake_client(monkeypatch)
    client = TestClient(api.app)

    response = client.post(
        "/api/v1/ask",
        json={"question": " 医疗器械软件安全性级别分为哪三级？ "},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["question"] == "医疗器械软件安全性级别分为哪三级？"
    assert payload["answer"].startswith("软件安全性级别")
    assert payload["references"][0]["document_name"] == "DOC003_test.pdf"
    assert payload["references"][0]["similarity"] == 0.91
    assert payload["elapsed_ms"] >= 0


def test_ask_rejects_blank_question():
    client = TestClient(api.app)

    response = client.post("/api/v1/ask", json={"question": "   "})

    assert response.status_code == 422


def test_stream_returns_stage_answer_and_done_events(monkeypatch):
    install_fake_client(monkeypatch)
    client = TestClient(api.app)

    response = client.post(
        "/api/v1/ask/stream",
        json={"question": "医疗器械软件安全性级别分为哪三级？"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: status" in response.text
    assert "event: answer" in response.text
    assert "event: done" in response.text
    assert "DOC003_test.pdf" in response.text


def test_health_returns_503_when_ragflow_is_unavailable(monkeypatch):
    def fail_to_connect():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(api, "get_ragflow_client", fail_to_connect)
    client = TestClient(api.app)

    response = client.get("/health")

    assert response.status_code == 503
    assert "RAGFlow 连接不可用" in response.json()["detail"]


def test_evidence_review_agent_returns_tool_trace(monkeypatch):
    fake = install_fake_client(monkeypatch)
    original_ask = fake.ask

    def ask_with_citation(question: str):
        result = original_ask(question)
        result["answer"] += " [ID:1]"
        return result

    fake.ask = ask_with_citation
    client = TestClient(api.app)

    response = client.post(
        "/api/v1/agent/review",
        json={"question": "医疗器械软件安全性级别分为哪三级？"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["citation_audit"]["status"] == "verified"
    assert payload["citation_audit"]["valid_citation_ids"] == [1]
    assert payload["citation_audit"]["cited_document_names"] == [
        "DOC003_test.pdf"
    ]
    assert [item["tool"] for item in payload["tool_trace"]] == [
        "ragflow_knowledge_qa",
        "citation_reference_audit",
    ]


def test_regulatory_agent_preserves_user_question(monkeypatch):
    install_fake_client(monkeypatch)
    client = TestClient(api.app)
    question = "软件安全性级别应如何判定？"

    response = client.post(
        "/api/v1/agents/regulatory",
        json={"question": question},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent"] == "regulatory"
    assert payload["question"] == question
    assert payload["tool_trace"][0]["tool"] == "ragflow_knowledge_qa"


def test_test_design_agent_has_specialized_identity(monkeypatch):
    install_fake_client(monkeypatch)
    client = TestClient(api.app)

    response = client.post(
        "/api/v1/agents/test-design",
        json={"question": "为软件登录权限设计测试方案。"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent"] == "test_design"
    assert "测试设计" in payload["purpose"]
    assert payload["references"][0]["document_name"] == "DOC003_test.pdf"


def test_evaluation_agent_endpoint_reuses_evidence_workflow(monkeypatch):
    fake = install_fake_client(monkeypatch)
    original_ask = fake.ask

    def ask_with_citation(question: str):
        result = original_ask(question)
        result["answer"] += " [ID:1]"
        return result

    fake.ask = ask_with_citation
    client = TestClient(api.app)

    response = client.post(
        "/api/v1/agents/evaluation",
        json={"question": "软件缺陷管理文件应包括什么？"},
    )

    assert response.status_code == 200
    assert response.json()["citation_audit"]["status"] == "verified"


def test_intent_router_recognizes_all_specialist_intents():
    assert route_intent("GB/T标准中的风险管理条款是什么？").intent == "regulatory"
    assert route_intent("请设计登录权限测试用例和预期结果").intent == "test_design"
    assert route_intent("请复核回答的引用正确性和幻觉风险").intent == "evaluation"


def test_intent_router_falls_back_to_regulatory():
    decision = route_intent("软件安全性级别分为哪三级？")

    assert decision.intent == "regulatory"
    assert decision.confidence == 0.4
    assert decision.matched_keywords == []


def test_routed_endpoint_selects_test_design_agent(monkeypatch):
    install_fake_client(monkeypatch)
    client = TestClient(api.app)

    response = client.post(
        "/api/v1/agents/route",
        json={"question": "请设计登录权限测试用例和预期结果。"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"]["selected_agent"] == "test_design"
    assert payload["result"]["agent"] == "test_design"
    assert payload["result"]["tool_trace"][0]["tool"] == "intent_router"


def test_controlled_workflow_rewrites_low_confidence_query(monkeypatch):
    fake = install_fake_client(monkeypatch)
    original_ask = fake.ask

    def ask_with_citation(question: str):
        result = original_ask(question)
        result["answer"] += " [ID:1]"
        return result

    fake.ask = ask_with_citation
    client = TestClient(api.app)

    response = client.post(
        "/api/v1/agents/workflow",
        json={
            "question": "软件发布前通常需要准备什么？",
            "allow_query_rewrite": True,
            "max_retries": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"]["selected_agent"] == "regulatory"
    assert payload["rewritten"] is True
    assert payload["completed"] is True
    assert payload["citation_audit"]["status"] == "verified"
    tools = [item["tool"] for item in payload["result"]["tool_trace"]]
    assert tools[:2] == ["intent_router", "low_confidence_query_rewrite"]
    assert payload["usage"]["source"] == "heuristic"


def test_controlled_workflow_keeps_high_confidence_test_route(monkeypatch):
    fake = install_fake_client(monkeypatch)
    original_ask = fake.ask

    def ask_with_citation(question: str):
        result = original_ask(question)
        result["answer"] += " [ID:1]"
        return result

    fake.ask = ask_with_citation
    client = TestClient(api.app)

    response = client.post(
        "/api/v1/agents/workflow",
        json={"question": "请设计登录权限测试用例和预期结果。"},
    )

    payload = response.json()
    assert payload["route"]["selected_agent"] == "test_design"
    assert payload["rewritten"] is False
    assert payload["retries"] == 0
    assert payload["completed"] is True


def test_memory_health_uses_redis_store(monkeypatch):
    memory = FakeMemoryStore()
    monkeypatch.setattr(api, "get_memory_store", lambda: memory)
    client = TestClient(api.app)

    response = client.get("/api/v1/memory/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "redis_connected": True}


def test_chat_reuses_conversation_history(monkeypatch):
    fake_client = install_fake_client(monkeypatch)
    memory = FakeMemoryStore()
    monkeypatch.setattr(api, "get_memory_store", lambda: memory)
    client = TestClient(api.app)

    first = client.post(
        "/api/v1/chat",
        json={"question": "软件安全性级别分为哪三级？"},
    )
    conversation_id = first.json()["conversation_id"]
    second = client.post(
        "/api/v1/chat",
        json={
            "question": "它们分别代表什么风险？",
            "conversation_id": conversation_id,
        },
    )

    assert first.status_code == 200
    assert first.json()["memory_turn_count"] == 2
    assert second.status_code == 200
    assert second.json()["memory_turn_count"] == 4
    assert second.json()["result"]["question"] == "它们分别代表什么风险？"
    assert "以下历史对话仅用于理解上下文" in fake_client.questions[-1]
    assert second.json()["result"]["tool_trace"][0]["tool"] == (
        "redis_conversation_memory"
    )


def test_conversation_history_can_be_read_and_deleted(monkeypatch):
    memory = FakeMemoryStore()
    awaitable_id = "conversation-test-001"
    memory.conversations[awaitable_id] = [
        ConversationMessage(
            role="user",
            content="测试问题",
            created_at="2026-08-25T00:00:00+00:00",
        )
    ]
    monkeypatch.setattr(api, "get_memory_store", lambda: memory)
    client = TestClient(api.app)

    history = client.get(f"/api/v1/conversations/{awaitable_id}")
    deleted = client.delete(f"/api/v1/conversations/{awaitable_id}")

    assert history.status_code == 200
    assert len(history.json()["messages"]) == 1
    assert deleted.json()["deleted"] is True


def test_evaluation_job_can_be_started_and_queried(monkeypatch):
    manager = FakeEvaluationManager()
    monkeypatch.setattr(api, "get_evaluation_manager", lambda: manager)
    client = TestClient(api.app)

    started = client.post(
        "/api/v1/evaluations/run",
        json={"dataset": "baseline", "limit": 1, "label": "api_smoke"},
    )
    job_id = started.json()["job_id"]
    status = client.get(f"/api/v1/evaluations/{job_id}")
    result = client.get(f"/api/v1/evaluations/{job_id}/result")

    assert started.status_code == 202
    assert started.json()["status"] == "queued"
    assert status.status_code == 200
    assert result.json()["summary"]["successful"] == 1


def test_evaluation_request_rejects_unregistered_dataset():
    client = TestClient(api.app)

    response = client.post(
        "/api/v1/evaluations/run",
        json={"dataset": "custom", "limit": 1},
    )

    assert response.status_code == 422


def test_metrics_exposes_http_and_ragflow_counters(monkeypatch):
    install_fake_client(monkeypatch)
    client = TestClient(api.app)

    ask_response = client.post(
        "/api/v1/ask",
        json={"question": "医疗器械软件安全性级别分为哪三级？"},
    )
    metrics_response = client.get("/metrics")

    assert ask_response.status_code == 200
    assert "X-Request-ID" in ask_response.headers
    assert metrics_response.status_code == 200
    assert "mdtr_http_requests_total" in metrics_response.text
    assert "mdtr_ragflow_calls_total" in metrics_response.text


def test_json_formatter_emits_structured_safe_fields():
    record = logging.LogRecord(
        name="medical_device_rag",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="http_request_completed",
        args=(),
        exc_info=None,
    )
    record.request_id = "request-test-001"
    record.route = "/health"
    record.status_code = 200

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "http_request_completed"
    assert payload["request_id"] == "request-test-001"
    assert payload["route"] == "/health"
    assert "question" not in payload

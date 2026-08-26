import asyncio
import json
from contextlib import asynccontextmanager
from functools import lru_cache
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.agents.evidence_review import EvidenceReviewAgent
from app.agents.router import route_intent
from app.agents.specialists import RegulatoryAgent, TestDesignAgent
from app.agents.workflow import execute_controlled_workflow
from app.evaluation_jobs import EvaluationJobManager
from app.graphrag import GraphRAGIndex
from app.memory import RedisConversationMemory, build_memory_context
from app.observability import (
    AGENT_ROUTES,
    ROUTER_CONFIDENCE,
    EVALUATION_JOBS,
    GRAPHRAG_DURATION,
    GRAPHRAG_PATH_HOPS,
    GRAPHRAG_SEARCHES,
    HTTP_DURATION,
    HTTP_REQUESTS,
    LOGGER,
    MEMORY_OPERATIONS,
    RAGFLOW_CALLS,
    RAGFLOW_DURATION,
)
from app.models import (
    AgentReviewRequest,
    AgentReviewResponse,
    AgentRouteRequest,
    AgentWorkflowRequest,
    AgentWorkflowResponse,
    AskRequest,
    AskResponse,
    ChatRequest,
    ChatResponse,
    ConversationHistory,
    EvaluationJob,
    EvaluationRunRequest,
    HealthResponse,
    GraphEvidenceItem,
    GraphPathItem,
    GraphRAGSearchRequest,
    GraphRAGSearchResponse,
    ReferenceItem,
    RoutedAgentResponse,
    SpecialistAgentResponse,
    ToolTrace,
)
from scripts.ragflow_client import RAGFlowClient
from app.tracing import configure_tracing, traced_span
from app.usage import build_usage_estimate


@lru_cache(maxsize=1)
def get_memory_store() -> RedisConversationMemory:
    return RedisConversationMemory.from_env()


@lru_cache(maxsize=1)
def get_evaluation_manager() -> EvaluationJobManager:
    return EvaluationJobManager(get_memory_store())


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    if get_memory_store.cache_info().currsize:
        await get_memory_store().close()


app = FastAPI(
    title="医疗器械控制软件测试知识库 API",
    description="基于 RAGFlow 的可追溯医疗器械软件测试知识问答接口。",
    version="1.6.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def observe_http(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    started_at = perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        elapsed_ms = round((perf_counter() - started_at) * 1000)
        route = getattr(request.scope.get("route"), "path", request.url.path)
        HTTP_REQUESTS.labels(request.method, route, str(status_code)).inc()
        HTTP_DURATION.labels(request.method, route).observe(
            perf_counter() - started_at
        )
        LOGGER.exception(
            "http_request_failed",
            extra={
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "route": route,
                "status_code": status_code,
                "elapsed_ms": elapsed_ms,
            },
        )
        raise

    elapsed_seconds = perf_counter() - started_at
    route = getattr(request.scope.get("route"), "path", request.url.path)
    HTTP_REQUESTS.labels(request.method, route, str(status_code)).inc()
    HTTP_DURATION.labels(request.method, route).observe(elapsed_seconds)
    response.headers["X-Request-ID"] = request_id
    LOGGER.info(
        "http_request_completed",
        extra={
            "event": "http_request",
            "request_id": request_id,
            "method": request.method,
            "route": route,
            "status_code": status_code,
            "elapsed_ms": round(elapsed_seconds * 1000),
        },
    )
    return response


@lru_cache(maxsize=1)
def get_ragflow_client() -> RAGFlowClient:
    """Reuse the HTTP session and resolved RAGFlow chat across requests."""
    return RAGFlowClient()


@lru_cache(maxsize=1)
def get_graphrag_index() -> GraphRAGIndex:
    """Load the optional graph index once per API process."""
    return GraphRAGIndex.from_path()


def normalize_reference(chunk: dict[str, Any]) -> ReferenceItem:
    similarity = chunk.get("similarity")
    try:
        similarity = float(similarity) if similarity is not None else None
    except (TypeError, ValueError):
        similarity = None

    positions = chunk.get("positions", [])
    if not isinstance(positions, list):
        positions = []

    return ReferenceItem(
        document_name=str(
            chunk.get("document_name")
            or chunk.get("doc_name")
            or ""
        ),
        similarity=similarity,
        content=str(chunk.get("content") or ""),
        chunk_id=str(chunk.get("chunk_id") or chunk.get("id") or ""),
        positions=positions,
    )


def build_ask_response(result: dict[str, Any], elapsed_ms: int) -> AskResponse:
    raw_references = result.get("references", [])
    if not isinstance(raw_references, list):
        raw_references = []

    question = str(result.get("question") or "")
    answer = str(result.get("answer") or "")
    return AskResponse(
        question=question,
        answer=answer,
        references=[
            normalize_reference(chunk)
            for chunk in raw_references
            if isinstance(chunk, dict)
        ],
        session_id=str(result.get("session_id") or ""),
        chat_id=str(result.get("chat_id") or ""),
        elapsed_ms=elapsed_ms,
        usage=build_usage_estimate(question, answer),
    )


async def execute_question(question: str) -> AskResponse:
    started_at = perf_counter()
    try:
        with traced_span(
            "ragflow.chat",
            {"ragflow.operation": "chat", "question.length": len(question)},
        ):
            client = await asyncio.to_thread(get_ragflow_client)
            result = await asyncio.to_thread(client.ask, question)
    except Exception as exc:
        RAGFLOW_CALLS.labels("failed").inc()
        RAGFLOW_DURATION.observe(perf_counter() - started_at)
        raise HTTPException(
            status_code=502,
            detail=f"RAGFlow 问答失败：{exc}",
        ) from exc

    elapsed_seconds = perf_counter() - started_at
    RAGFLOW_CALLS.labels("success").inc()
    RAGFLOW_DURATION.observe(elapsed_seconds)
    elapsed_ms = round(elapsed_seconds * 1000)
    return build_ask_response(result, elapsed_ms)


def sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    return {
        "name": app.title,
        "version": app.version,
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    try:
        client = await asyncio.to_thread(get_ragflow_client)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"RAGFlow 连接不可用：{exc}",
        ) from exc

    chat = client.chat if isinstance(client.chat, dict) else {}
    return HealthResponse(
        status="ok",
        ragflow_connected=True,
        chat_name=str(chat.get("name") or client.chat_name),
        chat_id=str(client.chat_id),
    )


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.post("/api/v1/ask", response_model=AskResponse, tags=["rag"])
async def ask(request: AskRequest) -> AskResponse:
    return await execute_question(request.question)


@app.post(
    "/api/v1/graphrag/search",
    response_model=GraphRAGSearchResponse,
    tags=["graphrag"],
)
async def graphrag_search(
    request: GraphRAGSearchRequest,
) -> GraphRAGSearchResponse:
    """Retrieve an auditable evidence path without changing /chat behavior."""

    started_at = perf_counter()
    try:
        with traced_span(
            "graphrag.search",
            {
                "question.length": len(request.question),
                "graphrag.top_k": request.top_k,
                "graphrag.max_hops": request.max_hops,
            },
        ):
            index = await asyncio.to_thread(get_graphrag_index)
            result = await asyncio.to_thread(
                index.search,
                request.question,
                request.top_k,
                request.max_hops,
            )
    except Exception as exc:
        GRAPHRAG_SEARCHES.labels("graph", "failed").inc()
        GRAPHRAG_DURATION.labels("graph").observe(perf_counter() - started_at)
        raise HTTPException(
            status_code=503,
            detail=f"GraphRAG 索引不可用：{exc}",
        ) from exc

    if result.paths:
        elapsed_seconds = perf_counter() - started_at
        GRAPHRAG_SEARCHES.labels("graph", "success").inc()
        GRAPHRAG_DURATION.labels("graph").observe(elapsed_seconds)
        for path in result.paths:
            GRAPHRAG_PATH_HOPS.observe(path["hop_count"])
        return GraphRAGSearchResponse(
            question=request.question,
            mode="graph",
            detected_entities=result.detected_entities,
            paths=[GraphPathItem(**item) for item in result.paths],
            evidence=[GraphEvidenceItem(**item) for item in result.evidence],
            confidence=result.confidence,
            elapsed_ms=round(elapsed_seconds * 1000),
        )

    if not request.fallback_to_ragflow:
        elapsed_seconds = perf_counter() - started_at
        GRAPHRAG_SEARCHES.labels("graph", "no_path").inc()
        GRAPHRAG_DURATION.labels("graph").observe(elapsed_seconds)
        return GraphRAGSearchResponse(
            question=request.question,
            mode="graph",
            detected_entities=result.detected_entities,
            evidence=[GraphEvidenceItem(**item) for item in result.evidence],
            confidence=result.confidence,
            fallback_reason="未发现可解释的多跳证据路径。",
            elapsed_ms=round(elapsed_seconds * 1000),
        )

    rag_response = await execute_question(request.question)
    elapsed_seconds = perf_counter() - started_at
    GRAPHRAG_SEARCHES.labels("ragflow_fallback", "success").inc()
    GRAPHRAG_DURATION.labels("ragflow_fallback").observe(elapsed_seconds)
    fallback_evidence = [
        GraphEvidenceItem(
            chunk_id=item.chunk_id,
            document_name=item.document_name,
            content=item.content,
            score=item.similarity or 0.0,
            source="ragflow",
        )
        for item in rag_response.references[: request.top_k]
    ]
    return GraphRAGSearchResponse(
        question=request.question,
        mode="ragflow_fallback",
        detected_entities=result.detected_entities,
        evidence=fallback_evidence,
        confidence=result.confidence,
        answer=rag_response.answer,
        fallback_reason="图索引未形成多跳路径，已安全回退到现有RAGFlow问答。",
        elapsed_ms=round(elapsed_seconds * 1000),
    )


@app.post("/api/v1/ask/stream", tags=["rag"])
async def ask_stream(request: AskRequest) -> StreamingResponse:
    async def event_stream():
        yield sse_event(
            "status",
            {"stage": "retrieving", "message": "正在检索知识库"},
        )
        try:
            response = await execute_question(request.question)
        except HTTPException as exc:
            yield sse_event("error", {"detail": exc.detail})
            return

        yield sse_event("answer", response.model_dump())
        yield sse_event(
            "done",
            {
                "session_id": response.session_id,
                "elapsed_ms": response.elapsed_ms,
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post(
    "/api/v1/agent/review",
    response_model=AgentReviewResponse,
    tags=["agent"],
)
async def review_with_agent(
    request: AgentReviewRequest,
) -> AgentReviewResponse:
    agent = EvidenceReviewAgent(ask_tool=execute_question)
    return await agent.run(request.question)


@app.post(
    "/api/v1/agents/regulatory",
    response_model=SpecialistAgentResponse,
    tags=["agents"],
)
async def ask_regulatory_agent(
    request: AgentReviewRequest,
) -> SpecialistAgentResponse:
    agent = RegulatoryAgent(ask_tool=execute_question)
    return await agent.run(request.question)


@app.post(
    "/api/v1/agents/test-design",
    response_model=SpecialistAgentResponse,
    tags=["agents"],
)
async def ask_test_design_agent(
    request: AgentReviewRequest,
) -> SpecialistAgentResponse:
    agent = TestDesignAgent(ask_tool=execute_question)
    return await agent.run(request.question)


@app.post(
    "/api/v1/agents/evaluation",
    response_model=AgentReviewResponse,
    tags=["agents"],
)
async def ask_evaluation_agent(
    request: AgentReviewRequest,
) -> AgentReviewResponse:
    agent = EvidenceReviewAgent(ask_tool=execute_question)
    return await agent.run(request.question)


async def execute_specialist_route(
    question: str,
    contextual_question: str | None = None,
) -> RoutedAgentResponse:
    decision = route_intent(question)
    AGENT_ROUTES.labels(decision.selected_agent).inc()
    ROUTER_CONFIDENCE.labels(decision.selected_agent).observe(
        decision.confidence
    )
    agent_question = contextual_question or question

    if decision.selected_agent == "test_design":
        result = await TestDesignAgent(ask_tool=execute_question).run(
            agent_question
        )
    elif decision.selected_agent == "evaluation":
        result = await EvidenceReviewAgent(ask_tool=execute_question).run(
            agent_question
        )
    else:
        result = await RegulatoryAgent(ask_tool=execute_question).run(
            agent_question
        )

    # Keep the public response focused on the current user question rather
    # than exposing the internal memory prompt.
    result.question = question
    result.tool_trace.insert(
        0,
        ToolTrace(
            tool="intent_router",
            status="success",
            elapsed_ms=0,
            summary=(
                f"识别为 {decision.intent}，路由至 "
                f"{decision.selected_agent} Agent。"
            ),
            details={
                "confidence": decision.confidence,
                "matched_keywords": decision.matched_keywords,
                "scores": decision.scores,
            },
        ),
    )
    return RoutedAgentResponse(route=decision, result=result)


@app.post(
    "/api/v1/agents/route",
    response_model=RoutedAgentResponse,
    tags=["agents"],
)
async def route_to_specialist_agent(
    request: AgentRouteRequest,
) -> RoutedAgentResponse:
    return await execute_specialist_route(request.question)


@app.post(
    "/api/v1/agents/workflow",
    response_model=AgentWorkflowResponse,
    tags=["agents"],
)
async def run_controlled_agent_workflow(
    request: AgentWorkflowRequest,
) -> AgentWorkflowResponse:
    return await execute_controlled_workflow(
        request.question,
        execute_question,
        allow_query_rewrite=request.allow_query_rewrite,
        max_retries=request.max_retries,
    )


@app.get("/api/v1/memory/health", tags=["memory"])
async def memory_health() -> dict[str, bool | str]:
    try:
        connected = await get_memory_store().ping()
    except Exception as exc:
        MEMORY_OPERATIONS.labels("ping", "failed").inc()
        raise HTTPException(
            status_code=503,
            detail=f"Redis 会话记忆不可用：{exc}",
        ) from exc
    MEMORY_OPERATIONS.labels("ping", "success").inc()
    return {"status": "ok", "redis_connected": connected}


@app.post(
    "/api/v1/chat",
    response_model=ChatResponse,
    tags=["memory"],
)
async def chat_with_memory(request: ChatRequest) -> ChatResponse:
    conversation_id = request.conversation_id or uuid4().hex
    memory = get_memory_store()
    try:
        history = await memory.get_history(conversation_id)
    except Exception as exc:
        MEMORY_OPERATIONS.labels("read", "failed").inc()
        raise HTTPException(
            status_code=503,
            detail=f"读取 Redis 会话记忆失败：{exc}",
        ) from exc

    MEMORY_OPERATIONS.labels("read", "success").inc()
    contextual_question = build_memory_context(request.question, history)
    routed = await execute_specialist_route(
        request.question,
        contextual_question,
    )
    try:
        await memory.append_exchange(
            conversation_id,
            request.question,
            routed.result.answer,
        )
    except Exception as exc:
        MEMORY_OPERATIONS.labels("write", "failed").inc()
        raise HTTPException(
            status_code=503,
            detail=f"写入 Redis 会话记忆失败：{exc}",
        ) from exc

    MEMORY_OPERATIONS.labels("write", "success").inc()
    routed.result.tool_trace.insert(
        0,
        ToolTrace(
            tool="redis_conversation_memory",
            status="success",
            elapsed_ms=0,
            summary=(
                f"读取 {len(history)} 条历史消息并保存本轮对话。"
            ),
            details={
                "conversation_id": conversation_id,
                "history_messages": len(history),
            },
        ),
    )
    return ChatResponse(
        conversation_id=conversation_id,
        memory_turn_count=len(history) + 2,
        route=routed.route,
        result=routed.result,
    )


@app.get(
    "/api/v1/conversations/{conversation_id}",
    response_model=ConversationHistory,
    tags=["memory"],
)
async def get_conversation(conversation_id: str) -> ConversationHistory:
    try:
        messages = await get_memory_store().get_history(conversation_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"读取 Redis 会话记忆失败：{exc}",
        ) from exc
    return ConversationHistory(
        conversation_id=conversation_id,
        messages=messages,
    )


@app.delete(
    "/api/v1/conversations/{conversation_id}",
    tags=["memory"],
)
async def delete_conversation(
    conversation_id: str,
) -> dict[str, bool | str]:
    try:
        deleted = await get_memory_store().delete(conversation_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"删除 Redis 会话记忆失败：{exc}",
        ) from exc
    return {"conversation_id": conversation_id, "deleted": deleted}


@app.post(
    "/api/v1/evaluations/run",
    response_model=EvaluationJob,
    tags=["evaluations"],
    status_code=202,
)
async def start_evaluation(request: EvaluationRunRequest) -> EvaluationJob:
    try:
        job = await get_evaluation_manager().start(request)
        EVALUATION_JOBS.labels("accepted").inc()
        return job
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"创建评测任务失败：{exc}",
        ) from exc


@app.get(
    "/api/v1/evaluations/{job_id}",
    response_model=EvaluationJob,
    tags=["evaluations"],
)
async def get_evaluation(job_id: str) -> EvaluationJob:
    try:
        job = await get_evaluation_manager().get(job_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"读取评测任务失败：{exc}",
        ) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="评测任务不存在或已过期")
    return job


@app.get(
    "/api/v1/evaluations/{job_id}/result",
    tags=["evaluations"],
)
async def get_evaluation_result(job_id: str) -> dict:
    manager = get_evaluation_manager()
    try:
        job = await manager.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail="评测任务不存在或已过期",
            )
        return await manager.load_result(job)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"读取评测结果失败：{exc}",
        ) from exc


# The call is intentionally last: all routes and middleware have been
# registered before OpenTelemetry wraps the ASGI application.
configure_tracing(app)

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class AskRequest(BaseModel):
    question: str = Field(
        min_length=2,
        max_length=2000,
        description="医疗器械软件测试或合规问题",
    )

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("问题去除空白后至少需要2个字符")
        return normalized


class ReferenceItem(BaseModel):
    document_name: str = ""
    similarity: float | None = None
    content: str = ""
    chunk_id: str = ""
    positions: list[Any] = Field(default_factory=list)


class UsageEstimate(BaseModel):
    source: Literal["provider", "heuristic", "unavailable"] = "unavailable"
    input_characters: int = 0
    output_characters: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_cost_usd: float | None = None
    pricing_configured: bool = False
    note: str = ""


class AskResponse(BaseModel):
    question: str
    answer: str
    references: list[ReferenceItem] = Field(default_factory=list)
    session_id: str = ""
    chat_id: str = ""
    elapsed_ms: int
    usage: UsageEstimate = Field(default_factory=UsageEstimate)


class HealthResponse(BaseModel):
    status: str
    ragflow_connected: bool
    chat_name: str = ""
    chat_id: str = ""


class AgentReviewRequest(AskRequest):
    """Question submitted to the evidence-review workflow."""


class ToolTrace(BaseModel):
    tool: str
    status: str
    elapsed_ms: int
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class CitationAudit(BaseModel):
    status: str
    reference_count: int
    citation_index_mode: str
    inline_citation_ids: list[int] = Field(default_factory=list)
    valid_citation_ids: list[int] = Field(default_factory=list)
    invalid_citation_ids: list[int] = Field(default_factory=list)
    cited_document_names: list[str] = Field(default_factory=list)
    note: str


class AgentReviewResponse(BaseModel):
    question: str
    answer: str
    references: list[ReferenceItem] = Field(default_factory=list)
    citation_audit: CitationAudit
    tool_trace: list[ToolTrace] = Field(default_factory=list)
    session_id: str = ""
    chat_id: str = ""
    elapsed_ms: int
    usage: UsageEstimate = Field(default_factory=UsageEstimate)


class SpecialistAgentResponse(BaseModel):
    agent: str
    purpose: str
    question: str
    answer: str
    references: list[ReferenceItem] = Field(default_factory=list)
    tool_trace: list[ToolTrace] = Field(default_factory=list)
    session_id: str = ""
    chat_id: str = ""
    elapsed_ms: int
    usage: UsageEstimate = Field(default_factory=UsageEstimate)


class AgentRouteRequest(AskRequest):
    """Question submitted to the automatic specialist router."""


class RouteDecision(BaseModel):
    intent: Literal["regulatory", "test_design", "evaluation"]
    selected_agent: Literal["regulatory", "test_design", "evaluation"]
    confidence: float = Field(ge=0, le=1)
    matched_keywords: list[str] = Field(default_factory=list)
    scores: dict[str, int] = Field(default_factory=dict)
    reason: str


class RoutedAgentResponse(BaseModel):
    route: RouteDecision
    result: SpecialistAgentResponse | AgentReviewResponse


class ChatRequest(AskRequest):
    conversation_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str


class ConversationHistory(BaseModel):
    conversation_id: str
    messages: list[ConversationMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    conversation_id: str
    memory_turn_count: int
    route: RouteDecision
    result: SpecialistAgentResponse | AgentReviewResponse


class AgentWorkflowRequest(AskRequest):
    allow_query_rewrite: bool = True
    max_retries: int = Field(default=1, ge=0, le=1)


class AgentWorkflowResponse(BaseModel):
    question: str
    effective_question: str
    rewritten: bool
    route: RouteDecision
    result: SpecialistAgentResponse | AgentReviewResponse
    citation_audit: CitationAudit
    retries: int = 0
    completed: bool
    completion_reason: str
    elapsed_ms: int
    usage: UsageEstimate = Field(default_factory=UsageEstimate)


class EvaluationRunRequest(BaseModel):
    dataset: Literal[
        "baseline",
        "holdout",
        "expansion",
        "practice",
        "blind",
        "agent",
    ]
    limit: int = Field(default=3, ge=1, le=204)
    question_ids: list[str] = Field(default_factory=list, max_length=204)
    label: str = Field(
        default="",
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]*$",
    )

    @field_validator("question_ids")
    @classmethod
    def normalize_question_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("question_ids不能包含重复题号")
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,15}", value) for value in normalized):
            raise ValueError("question_ids包含非法题号")
        return normalized


class EvaluationJob(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    request: EvaluationRunRequest
    created_at: str
    started_at: str = ""
    finished_at: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    json_result: str = ""
    csv_result: str = ""
    error: str = ""
    log_tail: str = ""

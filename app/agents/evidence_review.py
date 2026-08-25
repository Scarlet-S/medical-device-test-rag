import re
from collections.abc import Awaitable, Callable
from time import perf_counter

from app.models import (
    AgentReviewResponse,
    AskResponse,
    CitationAudit,
    ToolTrace,
)
from app.observability import (
    AGENT_DURATION,
    AGENT_ESTIMATED_COST_USD,
    AGENT_ESTIMATED_TOKENS,
    AGENT_EXECUTIONS,
    TOOL_CALLS,
    TOOL_DURATION,
)
from app.tracing import traced_span


CITATION_PATTERN = re.compile(r"\[ID\s*:\s*(\d+)\]", re.IGNORECASE)


def unique_in_order(values: list[int]) -> list[int]:
    return list(dict.fromkeys(values))


def audit_citations(answer: str, response: AskResponse) -> CitationAudit:
    citation_ids = unique_in_order(
        [int(value) for value in CITATION_PATTERN.findall(answer)]
    )
    reference_count = len(response.references)

    if not citation_ids:
        status = "missing_inline_citations" if reference_count else "no_evidence"
        return CitationAudit(
            status=status,
            reference_count=reference_count,
            citation_index_mode="unknown",
            note=(
                "已返回证据片段，但答案没有可解析的 [ID:n] 引用。"
                if reference_count
                else "答案和检索结果均未提供证据片段。"
            ),
        )

    # RAGFlow deployments may emit zero-based or one-based citation IDs.
    # ID 0 is an unambiguous signal for zero-based indexing; otherwise use
    # one-based indexing, which matches the user-facing citation convention.
    zero_based = 0 in citation_ids
    index_mode = "zero_based" if zero_based else "one_based"

    if zero_based:
        valid_ids = [value for value in citation_ids if 0 <= value < reference_count]
        invalid_ids = [value for value in citation_ids if value >= reference_count]
        reference_indexes = valid_ids
    else:
        valid_ids = [value for value in citation_ids if 1 <= value <= reference_count]
        invalid_ids = [
            value
            for value in citation_ids
            if value < 1 or value > reference_count
        ]
        reference_indexes = [value - 1 for value in valid_ids]

    document_names = list(
        dict.fromkeys(
            response.references[index].document_name
            for index in reference_indexes
            if response.references[index].document_name
        )
    )

    status = "verified" if not invalid_ids else "invalid_citations"
    note = (
        "所有内联引用编号均能映射到本轮返回的证据片段。"
        if not invalid_ids
        else "部分内联引用编号超出本轮证据片段范围。"
    )
    return CitationAudit(
        status=status,
        reference_count=reference_count,
        citation_index_mode=index_mode,
        inline_citation_ids=citation_ids,
        valid_citation_ids=valid_ids,
        invalid_citation_ids=invalid_ids,
        cited_document_names=document_names,
        note=note,
    )


class EvidenceReviewAgent:
    """Orchestrate RAG answering and deterministic citation verification."""

    def __init__(
        self,
        ask_tool: Callable[[str], Awaitable[AskResponse]],
    ) -> None:
        self.ask_tool = ask_tool

    async def run(self, question: str) -> AgentReviewResponse:
        workflow_started = perf_counter()
        trace: list[ToolTrace] = []

        answer_started = perf_counter()
        try:
            with traced_span("agent.evaluation", {"agent.name": "evaluation"}):
                with traced_span(
                    "tool.ragflow_knowledge_qa",
                    {"tool.name": "ragflow_knowledge_qa"},
                ):
                    response = await self.ask_tool(question)
            TOOL_CALLS.labels("ragflow_knowledge_qa", "success").inc()
        except Exception:
            TOOL_CALLS.labels("ragflow_knowledge_qa", "failed").inc()
            AGENT_EXECUTIONS.labels("evaluation", "failed").inc()
            AGENT_DURATION.labels("evaluation").observe(
                perf_counter() - workflow_started
            )
            raise
        finally:
            TOOL_DURATION.labels("ragflow_knowledge_qa").observe(
                perf_counter() - answer_started
            )
        trace.append(
            ToolTrace(
                tool="ragflow_knowledge_qa",
                status="success",
                elapsed_ms=round((perf_counter() - answer_started) * 1000),
                summary=(
                    f"生成回答并返回 {len(response.references)} 条候选证据。"
                ),
                details={
                    "session_id": response.session_id,
                    "reference_count": len(response.references),
                },
            )
        )

        audit_started = perf_counter()
        with traced_span(
            "tool.citation_reference_audit",
            {"tool.name": "citation_reference_audit"},
        ):
            audit = audit_citations(response.answer, response)
        audit_tool_status = "success" if audit.status == "verified" else "warning"
        TOOL_CALLS.labels("citation_reference_audit", audit_tool_status).inc()
        TOOL_DURATION.labels("citation_reference_audit").observe(
            perf_counter() - audit_started
        )
        trace.append(
            ToolTrace(
                tool="citation_reference_audit",
                status=(
                    audit_tool_status
                ),
                elapsed_ms=round((perf_counter() - audit_started) * 1000),
                summary=audit.note,
                details={
                    "citation_status": audit.status,
                    "valid_citation_ids": audit.valid_citation_ids,
                    "invalid_citation_ids": audit.invalid_citation_ids,
                },
            )
        )

        elapsed_ms = round((perf_counter() - workflow_started) * 1000)
        AGENT_EXECUTIONS.labels("evaluation", "success").inc()
        AGENT_DURATION.labels("evaluation").observe(elapsed_ms / 1000)
        AGENT_ESTIMATED_TOKENS.labels("evaluation", "input").inc(
            response.usage.estimated_input_tokens
        )
        AGENT_ESTIMATED_TOKENS.labels("evaluation", "output").inc(
            response.usage.estimated_output_tokens
        )
        if response.usage.estimated_cost_usd is not None:
            AGENT_ESTIMATED_COST_USD.labels("evaluation").inc(
                response.usage.estimated_cost_usd
            )

        return AgentReviewResponse(
            question=response.question,
            answer=response.answer,
            references=response.references,
            citation_audit=audit,
            tool_trace=trace,
            session_id=response.session_id,
            chat_id=response.chat_id,
            elapsed_ms=elapsed_ms,
            usage=response.usage,
        )

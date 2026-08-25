from collections.abc import Awaitable, Callable
from time import perf_counter

from app.agents.evidence_review import EvidenceReviewAgent, audit_citations
from app.agents.router import route_intent
from app.agents.specialists import RegulatoryAgent, TestDesignAgent
from app.models import (
    AgentReviewResponse,
    AgentWorkflowResponse,
    AskResponse,
    CitationAudit,
    RouteDecision,
    SpecialistAgentResponse,
    ToolTrace,
    UsageEstimate,
)
from app.observability import (
    AGENT_DURATION,
    AGENT_ESTIMATED_COST_USD,
    AGENT_ESTIMATED_TOKENS,
    AGENT_EXECUTIONS,
    AGENT_ROUTES,
    ROUTER_CONFIDENCE,
    TOOL_CALLS,
)
from app.tracing import traced_span


AgentResult = SpecialistAgentResponse | AgentReviewResponse
AskTool = Callable[[str], Awaitable[AskResponse]]


def rewrite_low_confidence_query(
    question: str,
    decision: RouteDecision,
) -> str:
    hints = {
        "regulatory": (
            "请优先检索医疗器械软件相关法规、指导原则、标准、质量管理规范"
            "或现场检查条款，并返回能够直接支持结论的来源。"
        ),
        "test_design": (
            "请检索与该风险或功能相关的验证要求，并据此组织测试目标、"
            "前置条件、步骤、预期结果和追溯依据。"
        ),
        "evaluation": (
            "请检索能够核验该回答的直接证据，并检查结论、引用、遗漏和"
            "无依据事实。"
        ),
    }
    return f"用户原问题：{question}\n\n检索改写要求：{hints[decision.selected_agent]}"


async def run_selected_agent(
    selected_agent: str,
    question: str,
    ask_tool: AskTool,
) -> AgentResult:
    if selected_agent == "test_design":
        return await TestDesignAgent(ask_tool=ask_tool).run(question)
    if selected_agent == "evaluation":
        return await EvidenceReviewAgent(ask_tool=ask_tool).run(question)
    return await RegulatoryAgent(ask_tool=ask_tool).run(question)


def result_citation_audit(result: AgentResult) -> CitationAudit:
    if isinstance(result, AgentReviewResponse):
        return result.citation_audit
    response = AskResponse(
        question=result.question,
        answer=result.answer,
        references=result.references,
        session_id=result.session_id,
        chat_id=result.chat_id,
        elapsed_ms=result.elapsed_ms,
        usage=result.usage,
    )
    return audit_citations(result.answer, response)


def combine_usage(*items: UsageEstimate) -> UsageEstimate:
    input_characters = sum(item.input_characters for item in items)
    output_characters = sum(item.output_characters for item in items)
    input_tokens = sum(item.estimated_input_tokens for item in items)
    output_tokens = sum(item.estimated_output_tokens for item in items)
    configured = any(item.pricing_configured for item in items)
    costs = [
        item.estimated_cost_usd
        for item in items
        if item.estimated_cost_usd is not None
    ]
    return UsageEstimate(
        source="heuristic",
        input_characters=input_characters,
        output_characters=output_characters,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        estimated_cost_usd=round(sum(costs), 8) if costs else None,
        pricing_configured=configured,
        note=(
            "多步工作流累计启发式token与费用估算；不是provider账单。"
            if configured
            else "多步工作流累计启发式token估算；未配置单价。"
        ),
    )


def needs_retry(result: AgentResult, audit: CitationAudit) -> bool:
    return bool(result.answer.strip()) and bool(result.references) and (
        audit.status != "verified"
    )


async def _execute_controlled_workflow(
    question: str,
    ask_tool: AskTool,
    *,
    allow_query_rewrite: bool = True,
    max_retries: int = 1,
    rewrite_threshold: float = 0.55,
) -> AgentWorkflowResponse:
    started_at = perf_counter()
    with traced_span("agent.workflow", {"workflow.name": "controlled_rag"}):
        decision = route_intent(question)
        AGENT_ROUTES.labels(decision.selected_agent).inc()
        ROUTER_CONFIDENCE.labels(decision.selected_agent).observe(
            decision.confidence
        )

        rewritten = allow_query_rewrite and decision.confidence < rewrite_threshold
        effective_question = (
            rewrite_low_confidence_query(question, decision)
            if rewritten
            else question
        )

        result = await run_selected_agent(
            decision.selected_agent,
            effective_question,
            ask_tool,
        )
        usage_items = [result.usage]
        audit = result_citation_audit(result)
        retries = 0

        if rewritten:
            TOOL_CALLS.labels("low_confidence_query_rewrite", "success").inc()
            result.tool_trace.insert(
                0,
                ToolTrace(
                    tool="low_confidence_query_rewrite",
                    status="success",
                    elapsed_ms=0,
                    summary=(
                        f"路由置信度 {decision.confidence:.2f} 低于 "
                        f"{rewrite_threshold:.2f}，追加领域检索约束。"
                    ),
                    details={
                        "original_question": question,
                        "rewrite_threshold": rewrite_threshold,
                    },
                ),
            )

        if max_retries and needs_retry(result, audit):
            retries = 1
            retry_prompt = (
                f"用户原问题：{question}\n\n"
                "上一轮回答已有证据，但引用编号缺失或无效。请重新回答，"
                "只使用本轮检索证据，并在每项主要结论后使用 [ID:n] 引用。"
            )
            with traced_span(
                "agent.workflow.evidence_retry",
                {"workflow.retry": 1},
            ):
                retry_result = await run_selected_agent(
                    decision.selected_agent,
                    retry_prompt,
                    ask_tool,
                )
            retry_audit = result_citation_audit(retry_result)
            usage_items.append(retry_result.usage)
            if retry_audit.status == "verified":
                TOOL_CALLS.labels("citation_quality_retry", "success").inc()
                retry_result.tool_trace.insert(
                    0,
                    ToolTrace(
                        tool="citation_quality_retry",
                        status="success",
                        elapsed_ms=retry_result.elapsed_ms,
                        summary="证据质量门禁触发一次重试，重试后引用通过核验。",
                        details={"previous_status": audit.status},
                    ),
                )
                result = retry_result
                audit = retry_audit
            else:
                TOOL_CALLS.labels("citation_quality_retry", "warning").inc()
                result.tool_trace.insert(
                    0,
                    ToolTrace(
                        tool="citation_quality_retry",
                        status="warning",
                        elapsed_ms=retry_result.elapsed_ms,
                        summary="证据质量门禁完成一次重试，但引用仍未完全通过。",
                        details={
                            "previous_status": audit.status,
                            "retry_status": retry_audit.status,
                        },
                    ),
                )

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

        completed = bool(result.answer.strip()) and bool(result.references) and (
            audit.status == "verified"
        )
        completion_reason = (
            "回答非空、存在检索证据且引用编号通过核验。"
            if completed
            else f"工作流完成，但证据门禁状态为 {audit.status}。"
        )
        AGENT_EXECUTIONS.labels(
            "controlled_workflow",
            "success" if completed else "warning",
        ).inc()

    elapsed_ms = round((perf_counter() - started_at) * 1000)
    usage = combine_usage(*usage_items)
    AGENT_DURATION.labels("controlled_workflow").observe(elapsed_ms / 1000)
    AGENT_ESTIMATED_TOKENS.labels("controlled_workflow", "input").inc(
        usage.estimated_input_tokens
    )
    AGENT_ESTIMATED_TOKENS.labels("controlled_workflow", "output").inc(
        usage.estimated_output_tokens
    )
    if usage.estimated_cost_usd is not None:
        AGENT_ESTIMATED_COST_USD.labels("controlled_workflow").inc(
            usage.estimated_cost_usd
        )
    return AgentWorkflowResponse(
        question=question,
        effective_question=effective_question,
        rewritten=rewritten,
        route=decision,
        result=result,
        citation_audit=audit,
        retries=retries,
        completed=completed,
        completion_reason=completion_reason,
        elapsed_ms=elapsed_ms,
        usage=usage,
    )


async def execute_controlled_workflow(
    question: str,
    ask_tool: AskTool,
    *,
    allow_query_rewrite: bool = True,
    max_retries: int = 1,
    rewrite_threshold: float = 0.55,
) -> AgentWorkflowResponse:
    started_at = perf_counter()
    try:
        return await _execute_controlled_workflow(
            question,
            ask_tool,
            allow_query_rewrite=allow_query_rewrite,
            max_retries=max_retries,
            rewrite_threshold=rewrite_threshold,
        )
    except Exception:
        AGENT_EXECUTIONS.labels("controlled_workflow", "failed").inc()
        AGENT_DURATION.labels("controlled_workflow").observe(
            perf_counter() - started_at
        )
        raise

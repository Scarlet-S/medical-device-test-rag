from collections.abc import Awaitable, Callable
from time import perf_counter

from app.models import AskResponse, SpecialistAgentResponse, ToolTrace
from app.observability import (
    AGENT_DURATION,
    AGENT_ESTIMATED_COST_USD,
    AGENT_ESTIMATED_TOKENS,
    AGENT_EXECUTIONS,
    TOOL_CALLS,
    TOOL_DURATION,
)
from app.tracing import traced_span


class KnowledgeSpecialistAgent:
    agent_name = "knowledge"
    purpose = "基于知识库回答问题"
    instructions = "仅依据检索证据回答，并提供来源引用。"

    def __init__(
        self,
        ask_tool: Callable[[str], Awaitable[AskResponse]],
    ) -> None:
        self.ask_tool = ask_tool

    def build_prompt(self, question: str) -> str:
        return (
            f"用户问题：{question}\n\n"
            f"当前角色：{self.agent_name}\n"
            f"任务要求：\n{self.instructions}\n"
            "如果检索证据不足，请明确说明证据不足，不得补充无来源事实。"
        )

    async def run(self, question: str) -> SpecialistAgentResponse:
        started_at = perf_counter()
        prompt = self.build_prompt(question)
        try:
            with traced_span(
                f"agent.{self.agent_name}",
                {"agent.name": self.agent_name},
            ):
                answer_started = perf_counter()
                try:
                    with traced_span(
                        "tool.ragflow_knowledge_qa",
                        {"tool.name": "ragflow_knowledge_qa"},
                    ):
                        result = await self.ask_tool(prompt)
                    TOOL_CALLS.labels(
                        "ragflow_knowledge_qa",
                        "success",
                    ).inc()
                except Exception:
                    TOOL_CALLS.labels(
                        "ragflow_knowledge_qa",
                        "failed",
                    ).inc()
                    raise
                finally:
                    TOOL_DURATION.labels("ragflow_knowledge_qa").observe(
                        perf_counter() - answer_started
                    )
        except Exception:
            AGENT_EXECUTIONS.labels(self.agent_name, "failed").inc()
            AGENT_DURATION.labels(self.agent_name).observe(
                perf_counter() - started_at
            )
            raise

        elapsed_ms = round((perf_counter() - started_at) * 1000)
        AGENT_EXECUTIONS.labels(self.agent_name, "success").inc()
        AGENT_DURATION.labels(self.agent_name).observe(elapsed_ms / 1000)
        AGENT_ESTIMATED_TOKENS.labels(self.agent_name, "input").inc(
            result.usage.estimated_input_tokens
        )
        AGENT_ESTIMATED_TOKENS.labels(self.agent_name, "output").inc(
            result.usage.estimated_output_tokens
        )
        if result.usage.estimated_cost_usd is not None:
            AGENT_ESTIMATED_COST_USD.labels(self.agent_name).inc(
                result.usage.estimated_cost_usd
            )

        return SpecialistAgentResponse(
            agent=self.agent_name,
            purpose=self.purpose,
            question=question,
            answer=result.answer,
            references=result.references,
            tool_trace=[
                ToolTrace(
                    tool="ragflow_knowledge_qa",
                    status="success",
                    elapsed_ms=elapsed_ms,
                    summary=(
                        f"{self.agent_name} 调用知识库并返回 "
                        f"{len(result.references)} 条候选证据。"
                    ),
                    details={
                        "agent": self.agent_name,
                        "reference_count": len(result.references),
                    },
                )
            ],
            session_id=result.session_id,
            chat_id=result.chat_id,
            elapsed_ms=elapsed_ms,
            usage=result.usage,
        )


class RegulatoryAgent(KnowledgeSpecialistAgent):
    agent_name = "regulatory"
    purpose = "医疗器械法规、指导原则和标准的证据化问答"
    instructions = """1. 优先回答法规、指导原则或标准中的直接要求。
2. 明确区分中国监管资料、FDA资料、推荐性标准和项目原创实践文档。
3. 输出应包含结论、依据和适用说明；没有直接依据时不得表述为强制要求。
4. 引用条款号、章节或文件名称时，必须能在本轮检索证据中找到。"""


class TestDesignAgent(KnowledgeSpecialistAgent):
    agent_name = "test_design"
    purpose = "根据法规证据生成医疗器械软件测试设计建议"
    instructions = """1. 根据检索证据提炼测试目标、风险点和验证要求。
2. 在证据允许时，按测试前置条件、测试步骤、预期结果和追溯依据组织输出。
3. 必须区分“资料直接要求”和“基于要求形成的测试建议”。
4. 不得虚构产品功能、测试数据、通过阈值、法规条款或强制性结论。"""

import asyncio
import os
from typing import Any

import requests
from mcp.server import MCPServer

from app.tracing import configure_tracing


API_BASE_URL = os.getenv(
    "AGENT_API_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")
HTTP_TIMEOUT_SECONDS = int(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "180"))

server = MCPServer(
    name="medical-device-test-rag",
    title="医疗器械软件测试知识库工具",
    description=(
        "将法规问答、测试设计、证据核查、意图路由和登记题集评测"
        "暴露为标准 MCP 工具。"
    ),
    instructions=(
        "优先调用只读知识工具；只有用户明确要求运行项目登记题集时，"
        "才调用 start_registered_evaluation。"
    ),
    version="1.3.0",
)


def _request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        f"{API_BASE_URL}{path}",
        json=payload,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Agent API 返回了非对象 JSON")
    return data


async def _request_async(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(_request, method, path, payload)


@server.tool(structured_output=True)
async def ask_regulatory(question: str) -> dict[str, Any]:
    """基于已入库监管资料回答法规、指导原则和标准问题，并返回引用。"""
    return await _request_async(
        "POST",
        "/api/v1/agents/regulatory",
        {"question": question},
    )


@server.tool(structured_output=True)
async def design_medical_software_tests(requirement: str) -> dict[str, Any]:
    """根据可检索依据生成测试目标、步骤、预期结果和追溯建议。"""
    return await _request_async(
        "POST",
        "/api/v1/agents/test-design",
        {"question": requirement},
    )


@server.tool(structured_output=True)
async def review_answer_evidence(question: str) -> dict[str, Any]:
    """运行知识问答并核查回答中的引用编号是否映射到实际证据。"""
    return await _request_async(
        "POST",
        "/api/v1/agent/review",
        {"question": question},
    )


@server.tool(structured_output=True)
async def route_medical_software_question(question: str) -> dict[str, Any]:
    """识别法规、测试设计或评测意图并调用相应专业 Agent。"""
    return await _request_async(
        "POST",
        "/api/v1/agents/route",
        {"question": question},
    )


@server.tool(structured_output=True)
async def run_controlled_medical_agent(question: str) -> dict[str, Any]:
    """运行路由、低置信度查询改写、专业Agent和证据质量门禁工作流。"""
    return await _request_async(
        "POST",
        "/api/v1/agents/workflow",
        {
            "question": question,
            "allow_query_rewrite": True,
            "max_retries": 1,
        },
    )


@server.tool(structured_output=True)
async def start_registered_evaluation(
    dataset: str,
    limit: int = 3,
    question_ids: list[str] | None = None,
    label: str = "mcp_evaluation",
) -> dict[str, Any]:
    """启动登记题集异步评测；dataset仅允许项目内白名单题集。"""
    return await _request_async(
        "POST",
        "/api/v1/evaluations/run",
        {
            "dataset": dataset,
            "limit": limit,
            "question_ids": question_ids or [],
            "label": label,
        },
    )


@server.tool(structured_output=True)
async def get_evaluation_status(job_id: str) -> dict[str, Any]:
    """查询异步评测任务状态、摘要和结果文件位置。"""
    return await _request_async(
        "GET",
        f"/api/v1/evaluations/{job_id}",
    )


def main() -> None:
    configure_tracing()
    server.run(
        transport="streamable-http",
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8001")),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()

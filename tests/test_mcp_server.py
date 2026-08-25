import asyncio

from app import mcp_server


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"agent": "regulatory", "answer": "测试回答"}


def test_mcp_exposes_bounded_domain_tools():
    tools = asyncio.run(mcp_server.server.list_tools())
    names = {tool.name for tool in tools}

    assert names == {
        "ask_regulatory",
        "design_medical_software_tests",
        "review_answer_evidence",
        "route_medical_software_question",
        "run_controlled_medical_agent",
        "start_registered_evaluation",
        "get_evaluation_status",
    }


def test_mcp_regulatory_tool_calls_fixed_api_path(monkeypatch):
    captured = {}

    def fake_request(method, url, json, timeout):
        captured.update(
            method=method,
            url=url,
            payload=json,
            timeout=timeout,
        )
        return FakeResponse()

    monkeypatch.setattr(mcp_server.requests, "request", fake_request)

    result = asyncio.run(mcp_server.ask_regulatory("法规要求是什么？"))

    assert result["agent"] == "regulatory"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/v1/agents/regulatory")
    assert captured["payload"] == {"question": "法规要求是什么？"}

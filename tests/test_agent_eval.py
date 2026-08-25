from scripts.run_agent_eval import macro_f1, percentile, summarize
from scripts.merge_agent_eval_retry import merge_records


def test_percentile_uses_nearest_rank():
    assert percentile([10, 20, 30, 40], 0.95) == 40
    assert percentile([], 0.95) == 0


def test_macro_f1_is_one_for_perfect_balanced_routes():
    values = ["regulatory", "test_design", "evaluation"]
    assert macro_f1(values, values) == 1.0


def test_agent_summary_unifies_route_tool_task_latency_and_cost():
    records = []
    for index, agent in enumerate(
        ("regulatory", "test_design", "evaluation"),
        start=1,
    ):
        records.append(
            {
                "status": "success",
                "expected_agent": agent,
                "actual_agent": agent,
                "route_hit": 1,
                "tool_recall": 1.0,
                "reference_coverage_hit": 1,
                "task_completed": 1,
                "elapsed_ms": index * 100,
                "estimated_input_tokens": 10,
                "estimated_output_tokens": 20,
                "estimated_cost_usd": 0.001,
            }
        )

    summary = summarize(records)

    assert summary["routing_accuracy"] == 1.0
    assert summary["routing_end_to_end_accuracy"] == 1.0
    assert summary["routing_macro_f1"] == 1.0
    assert summary["required_tool_recall"] == 1.0
    assert summary["execution_success_rate"] == 1.0
    assert summary["task_completion_rate"] == 1.0
    assert summary["p95_latency_ms"] == 300
    assert summary["estimated_cost_usd"] == 0.003


def test_agent_summary_separates_conditional_and_end_to_end_metrics():
    records = [
        {
            "status": "success",
            "expected_agent": "regulatory",
            "actual_agent": "regulatory",
            "route_hit": 1,
            "tool_recall": 1.0,
            "reference_coverage_hit": 1,
            "task_completed": 1,
            "elapsed_ms": 100,
            "estimated_input_tokens": 10,
            "estimated_output_tokens": 20,
            "estimated_cost_usd": None,
        },
        {
            "status": "failed",
            "expected_agent": "test_design",
            "actual_agent": "",
            "route_hit": 0,
            "tool_recall": 0.0,
            "reference_coverage_hit": 0,
            "task_completed": 0,
            "elapsed_ms": 30000,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "estimated_cost_usd": None,
        },
    ]

    summary = summarize(records)

    assert summary["execution_success_rate"] == 0.5
    assert summary["routing_accuracy"] == 1.0
    assert summary["routing_end_to_end_accuracy"] == 0.5
    assert summary["required_tool_recall"] == 1.0
    assert summary["required_tool_end_to_end_recall"] == 0.5
    assert summary["task_completion_rate_successful"] == 1.0
    assert summary["task_completion_rate"] == 0.5
    assert summary["request_p95_latency_ms"] == 30000


def test_merge_agent_retry_replaces_only_successful_matching_cases():
    base = [
        {
            "case_id": "A001",
            "question": "Q1",
            "expected_agent": "regulatory",
            "status": "failed",
        },
        {
            "case_id": "A002",
            "question": "Q2",
            "expected_agent": "evaluation",
            "status": "success",
        },
    ]
    retry = [
        {
            "case_id": "A001",
            "question": "Q1",
            "expected_agent": "regulatory",
            "status": "success",
        },
        {
            "case_id": "A002",
            "question": "Q2",
            "expected_agent": "evaluation",
            "status": "failed",
        },
    ]

    merged, replaced = merge_records(base, retry)

    assert replaced == ["A001"]
    assert merged[0]["status"] == "success"
    assert merged[1]["status"] == "success"

import argparse
import csv
import json
import math
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = (
    PROJECT_ROOT / "evaluation" / "agent" / "agent_evaluation_v1.json"
)
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
AGENT_API_BASE_URL = os.getenv(
    "AGENT_API_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")
HTTP_TIMEOUT_SECONDS = int(os.getenv("AGENT_EVAL_TIMEOUT_SECONDS", "60"))
MAX_ATTEMPTS = int(os.getenv("AGENT_EVAL_MAX_ATTEMPTS", "1"))


def percentile(values: list[float], percentage: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(len(ordered) * percentage))
    return round(ordered[rank - 1], 2)


def macro_f1(
    expected: list[str],
    predicted: list[str],
    labels: tuple[str, ...] | None = None,
) -> float:
    active_labels = labels or tuple(sorted(set(expected) | set(predicted)))
    if not active_labels:
        return 0.0
    scores = []
    for label in active_labels:
        true_positive = sum(
            want == label and got == label
            for want, got in zip(expected, predicted, strict=True)
        )
        false_positive = sum(
            want != label and got == label
            for want, got in zip(expected, predicted, strict=True)
        )
        false_negative = sum(
            want == label and got != label
            for want, got in zip(expected, predicted, strict=True)
        )
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append((2 * true_positive / denominator) if denominator else 0.0)
    return round(sum(scores) / len(scores), 4)


def read_cases(
    path: Path,
    limit: int,
    case_ids: set[str],
) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise RuntimeError("Agent评测集的cases字段必须是数组")

    required = {"case_id", "question", "expected_agent", "required_tools"}
    selected = []
    for case in cases:
        if not isinstance(case, dict) or not required.issubset(case):
            raise RuntimeError("Agent评测题缺少必要字段")
        case_id = str(case["case_id"]).strip().upper()
        if case_ids and case_id not in case_ids:
            continue
        selected.append({**case, "case_id": case_id})
        if len(selected) >= limit:
            break

    if case_ids:
        found = {case["case_id"] for case in selected}
        missing = sorted(case_ids - found)
        if missing:
            raise RuntimeError("未找到Agent评测题：" + ", ".join(missing))
    if not selected:
        raise RuntimeError("Agent评测集中没有可运行题目")
    return selected


def evaluate_case(
    session: requests.Session,
    case: dict[str, Any],
) -> dict[str, Any]:
    started_at = time.perf_counter()
    payload: dict[str, Any] = {}
    error = ""
    attempts = 0

    for attempts in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.post(
                f"{AGENT_API_BASE_URL}/api/v1/agents/workflow",
                json={
                    "question": case["question"],
                    "allow_query_rewrite": True,
                    "max_retries": 1,
                },
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            candidate = response.json()
            if not isinstance(candidate, dict):
                raise RuntimeError("工作流API返回非对象JSON")
            payload = candidate
            break
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    traces = result.get("tool_trace") if isinstance(result.get("tool_trace"), list) else []
    observed_tools = [
        str(item.get("tool") or "")
        for item in traces
        if isinstance(item, dict) and item.get("tool")
    ]
    successful_tools = [
        str(item.get("tool") or "")
        for item in traces
        if isinstance(item, dict)
        and item.get("tool")
        and item.get("status") == "success"
    ]
    required_tools = [str(value) for value in case.get("required_tools", [])]
    expected_agent = str(case["expected_agent"])
    actual_agent = str(route.get("selected_agent") or "")
    references = result.get("references") if isinstance(result.get("references"), list) else []
    min_references = int(case.get("min_references", 1))
    expected_rewrite = case.get("expect_rewrite")
    rewrite_hit = (
        None
        if expected_rewrite is None
        else bool(payload.get("rewritten")) is bool(expected_rewrite)
    )
    tool_recall = (
        sum(tool in observed_tools for tool in required_tools) / len(required_tools)
        if required_tools
        else 1.0
    )
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    status = "success" if payload else "failed"

    return {
        "case_id": case["case_id"],
        "question": case["question"],
        "expected_agent": expected_agent,
        "actual_agent": actual_agent,
        "status": status,
        "attempts": attempts,
        "route_hit": int(actual_agent == expected_agent),
        "route_confidence": route.get("confidence"),
        "required_tools": required_tools,
        "observed_tools": observed_tools,
        "successful_tools": successful_tools,
        "tool_recall": round(tool_recall, 4),
        "all_required_tools_called": int(tool_recall == 1.0),
        "all_observed_tools_successful": int(
            bool(observed_tools) and len(successful_tools) == len(observed_tools)
        ),
        "reference_count": len(references),
        "reference_coverage_hit": int(len(references) >= min_references),
        "expected_rewrite": expected_rewrite,
        "actual_rewrite": payload.get("rewritten"),
        "rewrite_hit": rewrite_hit,
        "task_completed": int(bool(payload.get("completed"))),
        "citation_status": (
            payload.get("citation_audit", {}).get("status", "")
            if isinstance(payload.get("citation_audit"), dict)
            else ""
        ),
        "elapsed_ms": elapsed_ms,
        "workflow_elapsed_ms": payload.get("elapsed_ms"),
        "estimated_input_tokens": usage.get("estimated_input_tokens", 0),
        "estimated_output_tokens": usage.get("estimated_output_tokens", 0),
        "estimated_cost_usd": usage.get("estimated_cost_usd"),
        "answer": result.get("answer", ""),
        "error": error if not payload else "",
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [record for record in records if record["status"] == "success"]
    total = len(records)
    expected = [record["expected_agent"] for record in successful]
    predicted = [record["actual_agent"] for record in successful]
    latencies = [float(record["elapsed_ms"]) for record in successful]
    costs = [
        float(record["estimated_cost_usd"])
        for record in successful
        if record["estimated_cost_usd"] is not None
    ]
    per_agent = {}
    for agent in ("regulatory", "test_design", "evaluation"):
        agent_records = [
            record for record in records if record["expected_agent"] == agent
        ]
        successful_agent_records = [
            record for record in agent_records if record["status"] == "success"
        ]
        agent_latencies = [
            float(record["elapsed_ms"]) for record in successful_agent_records
        ]
        per_agent[agent] = {
            "cases": len(agent_records),
            "successful_cases": len(successful_agent_records),
            "route_hits": sum(record["route_hit"] for record in agent_records),
            "task_completed": sum(
                record["task_completed"] for record in agent_records
            ),
            "p95_latency_ms": percentile(agent_latencies, 0.95),
            "estimated_cost_usd": round(
                sum(
                    float(record["estimated_cost_usd"])
                    for record in agent_records
                    if record["estimated_cost_usd"] is not None
                ),
                8,
            ),
        }

    return {
        "total": total,
        "successful": len(successful),
        "failed": total - len(successful),
        "execution_success_rate": round(len(successful) / total, 4)
        if total
        else 0.0,
        # Conditional quality metrics retain comparability with the v1 output.
        "routing_accuracy": round(
            sum(record["route_hit"] for record in successful) / len(successful),
            4,
        ) if successful else 0.0,
        "routing_end_to_end_accuracy": round(
            sum(record["route_hit"] for record in records) / total,
            4,
        ) if total else 0.0,
        "routing_macro_f1": macro_f1(expected, predicted) if successful else 0.0,
        "required_tool_recall": round(
            sum(record["tool_recall"] for record in successful) / len(successful),
            4,
        ) if successful else 0.0,
        "required_tool_end_to_end_recall": round(
            sum(record["tool_recall"] for record in records) / total,
            4,
        ) if total else 0.0,
        "reference_coverage_rate": round(
            sum(record["reference_coverage_hit"] for record in successful)
            / len(successful),
            4,
        ) if successful else 0.0,
        "task_completion_rate_successful": round(
            sum(record["task_completed"] for record in successful) / len(successful),
            4,
        ) if successful else 0.0,
        "task_completion_rate": round(
            sum(record["task_completed"] for record in records) / total,
            4,
        ) if total else 0.0,
        "p50_latency_ms": percentile(latencies, 0.50),
        "p95_latency_ms": percentile(latencies, 0.95),
        "request_p95_latency_ms": percentile(
            [float(record["elapsed_ms"]) for record in records],
            0.95,
        ),
        "estimated_input_tokens": sum(
            int(record["estimated_input_tokens"] or 0) for record in successful
        ),
        "estimated_output_tokens": sum(
            int(record["estimated_output_tokens"] or 0) for record in successful
        ),
        "estimated_cost_usd": round(sum(costs), 8) if costs else None,
        "actual_agent_distribution": dict(Counter(predicted)),
        "per_agent": per_agent,
    }


def save_results(
    records: list[dict[str, Any]],
    source_path: Path,
    label: str,
) -> tuple[Path, Path, dict[str, Any]]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    stem = f"agent_eval_{len(records)}{suffix}_{timestamp}"
    json_path = RESULTS_DIR / f"{stem}.json"
    csv_path = RESULTS_DIR / f"{stem}.csv"
    summary = summarize(records)
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "experiment_label": label,
                "source_dataset": str(source_path),
                "summary": summary,
                "results": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    fieldnames = [
        "case_id", "question", "expected_agent", "actual_agent", "status",
        "attempts", "route_hit", "route_confidence", "required_tools",
        "observed_tools", "tool_recall", "all_required_tools_called",
        "reference_count", "reference_coverage_hit", "expected_rewrite",
        "actual_rewrite", "rewrite_hit", "task_completed", "citation_status",
        "elapsed_ms", "workflow_elapsed_ms", "estimated_input_tokens",
        "estimated_output_tokens", "estimated_cost_usd", "error",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = {key: record.get(key, "") for key in fieldnames}
            row["required_tools"] = "|".join(record["required_tools"])
            row["observed_tools"] = "|".join(record["observed_tools"])
            writer.writerow(row)
    return json_path, csv_path, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--label", default="")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--case-id", default="")
    parser.add_argument("--case-ids", default="")
    args = parser.parse_args()
    if args.limit < 1:
        print("运行失败：--limit必须大于0")
        return 1

    dataset_path = args.dataset
    if not dataset_path.is_absolute():
        dataset_path = (PROJECT_ROOT / dataset_path).resolve()
    case_ids = {
        value.strip().upper()
        for value in f"{args.case_id},{args.case_ids}".split(",")
        if value.strip()
    }

    try:
        cases = read_cases(
            dataset_path,
            len(case_ids) if case_ids else args.limit,
            case_ids,
        )
    except Exception as exc:
        print(f"初始化失败：{exc}")
        return 1

    records = []
    with requests.Session() as session:
        for index, case in enumerate(cases, start=1):
            print(f"[{index}/{len(cases)}] {case['case_id']} {case['question']}")
            record = evaluate_case(session, case)
            records.append(record)
            print(
                f"  状态：{record['status']}｜路由：{record['route_hit']}｜"
                f"工具召回：{record['tool_recall']:.2f}｜"
                f"任务完成：{record['task_completed']}"
            )

    json_path, csv_path, summary = save_results(
        records,
        dataset_path,
        args.label,
    )
    print("=" * 60)
    print(f"总题数：{summary['total']}")
    print(f"成功：{summary['successful']}")
    print(f"失败：{summary['failed']}")
    print(f"API执行成功率：{summary['execution_success_rate']:.1%}")
    print(f"成功样本路由准确率：{summary['routing_accuracy']:.1%}")
    print(
        "端到端路由准确率："
        f"{summary['routing_end_to_end_accuracy']:.1%}"
    )
    print(f"路由Macro-F1：{summary['routing_macro_f1']:.1%}")
    print(f"成功样本工具召回率：{summary['required_tool_recall']:.1%}")
    print(
        "端到端工具召回率："
        f"{summary['required_tool_end_to_end_recall']:.1%}"
    )
    print(f"任务完成率：{summary['task_completion_rate']:.1%}")
    print(f"p95延迟：{summary['p95_latency_ms']:.0f} ms")
    print(f"JSON结果：{json_path}")
    print(f"CSV结果：{csv_path}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

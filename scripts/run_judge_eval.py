import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values

from ragflow_client import RAGFlowClient
from test_judge import (
    PROJECT_ROOT,
    build_prompt,
    find_latest_result,
    parse_judge_json,
)


RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
MAX_ATTEMPTS = 3


def load_source_records(path):
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    records = payload.get("results", [])

    if not records:
        raise RuntimeError("批量评测结果中没有题目记录")

    return records


def judge_record(client, record):
    started = time.perf_counter()
    raw_output = ""
    score = None
    error = ""
    attempts = 0

    for attempts in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.ask(build_prompt(record))
            raw_output = response.get("answer", "")

            if not raw_output.strip():
                raise ValueError("裁判助手返回了空答案")

            score = parse_judge_json(raw_output)
            break
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

            if attempts < MAX_ATTEMPTS:
                print(f"  第{attempts}次未成功，2秒后重试……")
                time.sleep(2)

    elapsed = round(time.perf_counter() - started, 2)

    return {
        "question_id": record.get("question_id", ""),
        "question": record.get("question", ""),
        "expected_document": record.get("expected_document", ""),
        "expected_location": record.get("expected_location", ""),
        "status": "success" if score else "failed",
        "attempts": attempts,
        "elapsed_seconds": elapsed,
        "citation_correct": (
            score["citation_correct"] if score else ""
        ),
        "answer_accuracy": (
            score["answer_accuracy"] if score else ""
        ),
        "hallucination": (
            score["hallucination"] if score else ""
        ),
        "reason": score.get("reason", "") if score else "",
        "raw_judge_output": raw_output,
        "error": "" if score else error,
    }


def save_results(records, source_path):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"judge_eval_{len(records)}_{timestamp}"
    json_path = RESULTS_DIR / f"{base_name}.json"
    csv_path = RESULTS_DIR / f"{base_name}.csv"

    successful = [
        record for record in records
        if record["status"] == "success"
    ]
    citation_total = sum(
        record["citation_correct"] for record in successful
    )
    accuracy_total = sum(
        record["answer_accuracy"] for record in successful
    )
    hallucination_total = sum(
        record["hallucination"] for record in successful
    )
    successful_count = len(successful)

    summary = {
        "total": len(records),
        "successful": successful_count,
        "failed": len(records) - successful_count,
        "citation_correct": citation_total,
        "citation_correct_rate": (
            round(citation_total / successful_count, 4)
            if successful_count else 0
        ),
        "answer_accuracy_points": accuracy_total,
        "answer_accuracy_max_points": successful_count * 2,
        "answer_accuracy_rate": (
            round(accuracy_total / (successful_count * 2), 4)
            if successful_count else 0
        ),
        "hallucinations": hallucination_total,
        "hallucination_rate": (
            round(hallucination_total / successful_count, 4)
            if successful_count else 0
        ),
    }

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
                "source_result": str(source_path),
                "summary": summary,
                "results": records,
            },
            file,
            ensure_ascii=False,
            indent=2,
        )

    fieldnames = [
        "question_id",
        "question",
        "expected_document",
        "expected_location",
        "status",
        "attempts",
        "elapsed_seconds",
        "citation_correct",
        "answer_accuracy",
        "hallucination",
        "reason",
        "raw_judge_output",
        "error",
    ]

    with csv_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    return json_path, csv_path, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="本次裁判的题目数量，默认5题",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="指定batch_eval JSON；省略时使用最新50题结果",
    )
    args = parser.parse_args()

    if args.limit < 1:
        print("运行失败：--limit必须大于0")
        return 1

    source_path = (
        args.input.resolve()
        if args.input
        else find_latest_result()
    )

    try:
        source_records = load_source_records(source_path)
        selected_records = source_records[: args.limit]

        env = dotenv_values(PROJECT_ROOT / ".env")
        judge_name = env.get("RAGFLOW_JUDGE_CHAT_NAME")

        if not judge_name:
            raise RuntimeError(
                ".env缺少RAGFLOW_JUDGE_CHAT_NAME"
            )

        client = RAGFlowClient(chat_name=judge_name)
    except Exception as exc:
        print(f"初始化失败：{exc}")
        return 1

    judged_records = []

    for index, record in enumerate(selected_records, start=1):
        print(
            f"[{index}/{len(selected_records)}] "
            f"{record.get('question_id', '')} "
            f"{record.get('question', '')}"
        )

        judged = judge_record(client, record)
        judged_records.append(judged)

        print(
            f"  状态：{judged['status']}｜"
            f"尝试：{judged['attempts']}｜"
            f"引用：{judged['citation_correct']}｜"
            f"准确度：{judged['answer_accuracy']}｜"
            f"幻觉：{judged['hallucination']}"
        )

    json_path, csv_path, summary = save_results(
        judged_records,
        source_path,
    )

    print("=" * 60)
    print(f"总题数：{summary['total']}")
    print(f"成功：{summary['successful']}")
    print(f"失败：{summary['failed']}")
    print(
        "引用正确："
        f"{summary['citation_correct']}/"
        f"{summary['successful']}"
    )
    print(
        "回答准确度："
        f"{summary['answer_accuracy_points']}/"
        f"{summary['answer_accuracy_max_points']}"
    )
    print(
        "幻觉："
        f"{summary['hallucinations']}/"
        f"{summary['successful']}"
    )
    print(f"JSON结果：{json_path}")
    print(f"CSV结果：{csv_path}")

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

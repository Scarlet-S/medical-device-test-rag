import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"


def load_payload(path):
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    records = payload.get("results", [])
    if not records:
        raise RuntimeError(f"结果文件没有题目记录：{path}")
    return payload, records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--retry", type=Path, required=True)
    parser.add_argument("--label", default="merged")
    args = parser.parse_args()

    base_path = args.base.resolve()
    retry_path = args.retry.resolve()
    base_payload, base_records = load_payload(base_path)
    _, retry_records = load_payload(retry_path)

    retry_by_id = {
        record["question_id"]: record
        for record in retry_records
        if record.get("status") == "success"
    }
    if not retry_by_id:
        raise RuntimeError("补测文件中没有成功记录")

    base_ids = {
        record.get("question_id")
        for record in base_records
    }
    unknown_ids = set(retry_by_id) - base_ids
    if unknown_ids:
        raise RuntimeError(
            "补测题目不在原始结果中："
            + "、".join(sorted(unknown_ids))
        )

    merged = []
    replaced = []
    for record in base_records:
        question_id = record.get("question_id")
        retry_record = retry_by_id.get(question_id)
        if retry_record and record.get("status") != "success":
            merged.append(retry_record)
            replaced.append(question_id)
        else:
            merged.append(record)

    if not replaced:
        raise RuntimeError("没有找到可由成功补测记录替换的失败题")

    successful = [
        record for record in merged
        if record.get("status") == "success"
    ]
    summary = {
        "total": len(merged),
        "successful": len(successful),
        "failed": len(merged) - len(successful),
        "top1_hits": sum(
            int(record.get("top1_hit", 0))
            for record in successful
        ),
        "top3_hits": sum(
            int(record.get("top3_hit", 0))
            for record in successful
        ),
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(
        char if char.isalnum() or char in "_-" else "_"
        for char in args.label
    ).strip("_")
    stem = f"batch_eval_{len(merged)}_{safe_label}_{timestamp}"
    json_path = RESULTS_DIR / f"{stem}.json"
    csv_path = RESULTS_DIR / f"{stem}.csv"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "experiment_label": args.label,
        "source_workbook": base_payload.get("source_workbook", ""),
        "merge_info": {
            "base_result": str(base_path),
            "retry_result": str(retry_path),
            "replaced_question_ids": replaced,
        },
        "summary": summary,
        "results": merged,
    }
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    fieldnames = [
        "question_id",
        "expected_document",
        "question",
        "expected_location",
        "reference_answer",
        "status",
        "attempts",
        "elapsed_seconds",
        "answer",
        "actual_top1_document",
        "top1_hit",
        "top3_hit",
        "reference_count",
        "top3_documents",
        "session_id",
        "error",
    ]
    with csv_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for record in merged:
            row = {
                key: record.get(key, "")
                for key in fieldnames
            }
            row["top3_documents"] = "|".join(
                reference.get("document_code", "")
                for reference in record.get("references", [])[:3]
            )
            writer.writerow(row)

    print("=" * 60)
    print(f"合并题数：{summary['total']}")
    print(f"成功：{summary['successful']}")
    print(f"失败：{summary['failed']}")
    print(f"Top1命中：{summary['top1_hits']}")
    print(f"Top3命中：{summary['top3_hits']}")
    print(f"替换题目：{'、'.join(replaced)}")
    print(f"JSON结果：{json_path}")
    print(f"CSV结果：{csv_path}")


if __name__ == "__main__":
    main()

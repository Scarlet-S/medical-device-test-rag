import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
ACCEPTABLE_CONFIG = (
    PROJECT_ROOT
    / "evaluation"
    / "config"
    / "acceptable_documents.json"
)


def load_payload(path):
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    records = {
        item["question_id"]: item
        for item in payload.get("results", [])
        if item.get("status") == "success"
    }

    if not records:
        raise RuntimeError(f"结果文件没有成功题目：{path}")

    return payload, records


def load_acceptable_documents():
    if not ACCEPTABLE_CONFIG.exists():
        return {}

    with ACCEPTABLE_CONFIG.open("r", encoding="utf-8") as file:
        return json.load(file)


def document_codes(record):
    return [
        reference.get("document_code", "")
        for reference in record.get("references", [])
    ]


def first_similarity(record):
    references = record.get("references", [])

    if not references:
        return ""

    return references[0].get("similarity", "")


def expected_rank(record):
    expected = record.get("expected_document", "")

    for index, code in enumerate(
        document_codes(record),
        start=1,
    ):
        if code == expected:
            return index

    return ""


def acceptable_codes(record, config):
    question_id = record["question_id"]
    expected = record.get("expected_document", "")
    configured = config.get(question_id, [])

    return set(configured or [expected]) | {expected}


def hit_at(record, accepted, limit):
    return int(
        bool(accepted.intersection(document_codes(record)[:limit]))
    )


def compare_records(baseline_records, candidate_records, config):
    rows = []
    common_ids = sorted(
        set(baseline_records) & set(candidate_records)
    )

    for question_id in common_ids:
        baseline = baseline_records[question_id]
        candidate = candidate_records[question_id]
        accepted = acceptable_codes(baseline, config)

        baseline_top1 = int(baseline.get("top1_hit", 0))
        candidate_top1 = int(candidate.get("top1_hit", 0))
        baseline_top3 = int(baseline.get("top3_hit", 0))
        candidate_top3 = int(candidate.get("top3_hit", 0))
        baseline_acceptable_top1 = hit_at(
            baseline,
            accepted,
            1,
        )
        candidate_acceptable_top1 = hit_at(
            candidate,
            accepted,
            1,
        )
        baseline_acceptable_top3 = hit_at(
            baseline,
            accepted,
            3,
        )
        candidate_acceptable_top3 = hit_at(
            candidate,
            accepted,
            3,
        )

        rows.append(
            {
                "question_id": question_id,
                "expected_document": baseline.get(
                    "expected_document",
                    "",
                ),
                "acceptable_documents": "|".join(
                    sorted(accepted)
                ),
                "question": baseline.get("question", ""),
                "baseline_top1_document": baseline.get(
                    "actual_top1_document",
                    "",
                ),
                "candidate_top1_document": candidate.get(
                    "actual_top1_document",
                    "",
                ),
                "baseline_expected_rank": expected_rank(
                    baseline
                ),
                "candidate_expected_rank": expected_rank(
                    candidate
                ),
                "baseline_top1_similarity": first_similarity(
                    baseline
                ),
                "candidate_top1_similarity": first_similarity(
                    candidate
                ),
                "baseline_strict_top1": baseline_top1,
                "candidate_strict_top1": candidate_top1,
                "strict_top1_change": (
                    candidate_top1 - baseline_top1
                ),
                "baseline_strict_top3": baseline_top3,
                "candidate_strict_top3": candidate_top3,
                "strict_top3_change": (
                    candidate_top3 - baseline_top3
                ),
                "baseline_acceptable_top1": (
                    baseline_acceptable_top1
                ),
                "candidate_acceptable_top1": (
                    candidate_acceptable_top1
                ),
                "acceptable_top1_change": (
                    candidate_acceptable_top1
                    - baseline_acceptable_top1
                ),
                "baseline_acceptable_top3": (
                    baseline_acceptable_top3
                ),
                "candidate_acceptable_top3": (
                    candidate_acceptable_top3
                ),
                "acceptable_top3_change": (
                    candidate_acceptable_top3
                    - baseline_acceptable_top3
                ),
            }
        )

    return rows


def count(rows, field):
    return sum(row[field] for row in rows)


def changed_ids(rows, field, value):
    return [
        row["question_id"]
        for row in rows
        if row[field] == value
    ]


def format_ids(values):
    return "、".join(values) if values else "无"


def save_csv(rows):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = (
        RESULTS_DIR
        / f"retrieval_experiment_comparison_{timestamp}.csv"
    )

    with output_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0].keys()),
        )
        writer.writeheader()
        writer.writerows(rows)

    return output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help="基线批量评测JSON",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        required=True,
        help="候选参数批量评测JSON",
    )
    args = parser.parse_args()

    try:
        baseline_payload, baseline_records = load_payload(
            args.baseline.resolve()
        )
        candidate_payload, candidate_records = load_payload(
            args.candidate.resolve()
        )
        config = load_acceptable_documents()
        rows = compare_records(
            baseline_records,
            candidate_records,
            config,
        )
    except Exception as exc:
        print(f"比较失败：{exc}")
        return 1

    if not rows:
        print("比较失败：两个批次没有共同题目")
        return 1

    output_path = save_csv(rows)
    total = len(rows)
    baseline_label = baseline_payload.get(
        "experiment_label",
        "baseline",
    ) or "baseline"
    candidate_label = candidate_payload.get(
        "experiment_label",
        "candidate",
    ) or "candidate"

    print("=" * 60)
    print(f"比较题数：{total}")
    print(f"基线标签：{baseline_label}")
    print(f"候选标签：{candidate_label}")
    print(
        "严格Top1："
        f"{count(rows, 'baseline_strict_top1')}/{total}"
        " -> "
        f"{count(rows, 'candidate_strict_top1')}/{total}"
    )
    print(
        "严格Top3："
        f"{count(rows, 'baseline_strict_top3')}/{total}"
        " -> "
        f"{count(rows, 'candidate_strict_top3')}/{total}"
    )
    print(
        "可接受Top1："
        f"{count(rows, 'baseline_acceptable_top1')}/{total}"
        " -> "
        f"{count(rows, 'candidate_acceptable_top1')}/{total}"
    )
    print(
        "可接受Top3："
        f"{count(rows, 'baseline_acceptable_top3')}/{total}"
        " -> "
        f"{count(rows, 'candidate_acceptable_top3')}/{total}"
    )
    print(
        "严格Top1提升："
        + format_ids(
            changed_ids(rows, "strict_top1_change", 1)
        )
    )
    print(
        "严格Top1下降："
        + format_ids(
            changed_ids(rows, "strict_top1_change", -1)
        )
    )
    print(
        "严格Top3提升："
        + format_ids(
            changed_ids(rows, "strict_top3_change", 1)
        )
    )
    print(
        "严格Top3下降："
        + format_ids(
            changed_ids(rows, "strict_top3_change", -1)
        )
    )
    print(
        "可接受Top1提升："
        + format_ids(
            changed_ids(rows, "acceptable_top1_change", 1)
        )
    )
    print(
        "可接受Top1下降："
        + format_ids(
            changed_ids(rows, "acceptable_top1_change", -1)
        )
    )
    print(f"明细结果：{output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import argparse
import csv
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
CONFIG_PATH = (
    PROJECT_ROOT
    / "evaluation"
    / "config"
    / "acceptable_documents.json"
)


def extract_doc_code(value):
    if not value:
        return ""

    match = re.search(r"DOC\d{3}", str(value), re.IGNORECASE)
    return match.group(0).upper() if match else ""


def find_latest_result():
    candidates = sorted(
        RESULTS_DIR.glob("batch_eval_50_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not candidates:
        raise RuntimeError("未找到50题批量评测JSON结果")

    return candidates[0]


def load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--result",
        type=Path,
        help="指定批量评测JSON；不填写则读取最新50题结果",
    )
    args = parser.parse_args()

    result_path = (
        args.result.resolve()
        if args.result
        else find_latest_result()
    )

    payload = load_json(result_path)
    acceptable_config = load_json(CONFIG_PATH)

    rows = []

    for record in payload["results"]:
        question_id = record["question_id"]
        expected_code = extract_doc_code(
            record["expected_document"]
        )

        acceptable_codes = {
            expected_code,
            *[
                extract_doc_code(code)
                for code in acceptable_config.get(
                    question_id,
                    [],
                )
            ],
        }
        acceptable_codes.discard("")

        retrieved_codes = [
            reference.get("document_code")
            or extract_doc_code(
                reference.get("document_name")
            )
            for reference in record.get("references", [])
        ]

        strict_top1 = int(record.get("top1_hit", 0))
        strict_top3 = int(record.get("top3_hit", 0))

        acceptable_top1 = int(
            bool(retrieved_codes)
            and retrieved_codes[0] in acceptable_codes
        )
        acceptable_top3 = int(
            any(
                code in acceptable_codes
                for code in retrieved_codes[:3]
            )
        )

        rows.append(
            {
                "question_id": question_id,
                "expected_document": expected_code,
                "acceptable_documents": "|".join(
                    sorted(acceptable_codes)
                ),
                "actual_top1_document": (
                    retrieved_codes[0]
                    if retrieved_codes
                    else ""
                ),
                "top3_documents": "|".join(
                    retrieved_codes[:3]
                ),
                "strict_top1": strict_top1,
                "strict_top3": strict_top3,
                "acceptable_top1": acceptable_top1,
                "acceptable_top3": acceptable_top3,
                "top1_rescued": int(
                    strict_top1 == 0
                    and acceptable_top1 == 1
                ),
                "top3_rescued": int(
                    strict_top3 == 0
                    and acceptable_top3 == 1
                ),
            }
        )

    total = len(rows)
    strict_top1_hits = sum(
        row["strict_top1"] for row in rows
    )
    strict_top3_hits = sum(
        row["strict_top3"] for row in rows
    )
    acceptable_top1_hits = sum(
        row["acceptable_top1"] for row in rows
    )
    acceptable_top3_hits = sum(
        row["acceptable_top3"] for row in rows
    )

    rescued_top1 = [
        row["question_id"]
        for row in rows
        if row["top1_rescued"]
    ]
    rescued_top3 = [
        row["question_id"]
        for row in rows
        if row["top3_rescued"]
    ]

    output_path = (
        RESULTS_DIR
        / f"acceptable_hits_{result_path.stem}.csv"
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

    print("=" * 60)
    print(f"评测题数：{total}")
    print(
        f"严格Top1：{strict_top1_hits}/{total}"
        f"（{strict_top1_hits / total:.1%}）"
    )
    print(
        f"可接受Top1：{acceptable_top1_hits}/{total}"
        f"（{acceptable_top1_hits / total:.1%}）"
    )
    print(
        f"严格Top3：{strict_top3_hits}/{total}"
        f"（{strict_top3_hits / total:.1%}）"
    )
    print(
        f"可接受Top3：{acceptable_top3_hits}/{total}"
        f"（{acceptable_top3_hits / total:.1%}）"
    )
    print(
        "Top1纠正题目："
        + ("、".join(rescued_top1) if rescued_top1 else "无")
    )
    print(
        "Top3纠正题目："
        + ("、".join(rescued_top3) if rescued_top3 else "无")
    )
    print(f"明细结果：{output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
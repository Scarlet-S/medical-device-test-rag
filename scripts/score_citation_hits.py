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


def extract_citation_ids(answer):
    citation_ids = []

    for value in re.findall(r"\[ID:(\d+)\]", answer or ""):
        citation_id = int(value)

        if citation_id not in citation_ids:
            citation_ids.append(citation_id)

    return citation_ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--result",
        type=Path,
        help="指定批测JSON；不填写则读取最新50题结果",
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

        references = record.get("references", [])
        citation_ids = extract_citation_ids(
            record.get("answer", "")
        )

        cited_documents = []

        for citation_id in citation_ids:
            if citation_id >= len(references):
                continue

            reference = references[citation_id]
            document_code = (
                reference.get("document_code")
                or extract_doc_code(
                    reference.get("document_name")
                )
            )

            if document_code:
                cited_documents.append(document_code)

        citation_top1_document = (
            cited_documents[0]
            if cited_documents
            else ""
        )

        strict_top1 = int(
            bool(cited_documents)
            and cited_documents[0] == expected_code
        )
        strict_top3 = int(
            expected_code in cited_documents[:3]
        )

        acceptable_top1 = int(
            bool(cited_documents)
            and cited_documents[0] in acceptable_codes
        )
        acceptable_top3 = int(
            any(
                code in acceptable_codes
                for code in cited_documents[:3]
            )
        )

        rows.append(
            {
                "question_id": question_id,
                "expected_document": expected_code,
                "acceptable_documents": "|".join(
                    sorted(acceptable_codes)
                ),
                "citation_ids": "|".join(
                    str(value) for value in citation_ids
                ),
                "cited_documents": "|".join(
                    cited_documents
                ),
                "citation_top1_document": (
                    citation_top1_document
                ),
                "strict_citation_top1": strict_top1,
                "strict_citation_top3": strict_top3,
                "acceptable_citation_top1": (
                    acceptable_top1
                ),
                "acceptable_citation_top3": (
                    acceptable_top3
                ),
                "citation_count": len(cited_documents),
            }
        )

    total = len(rows)
    strict_top1_hits = sum(
        row["strict_citation_top1"] for row in rows
    )
    strict_top3_hits = sum(
        row["strict_citation_top3"] for row in rows
    )
    acceptable_top1_hits = sum(
        row["acceptable_citation_top1"] for row in rows
    )
    acceptable_top3_hits = sum(
        row["acceptable_citation_top3"] for row in rows
    )

    no_citation = [
        row["question_id"]
        for row in rows
        if row["citation_count"] == 0
    ]

    output_path = (
        RESULTS_DIR
        / f"citation_hits_{result_path.stem}.csv"
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
        f"严格引用Top1：{strict_top1_hits}/{total}"
        f"（{strict_top1_hits / total:.1%}）"
    )
    print(
        f"可接受引用Top1：{acceptable_top1_hits}/{total}"
        f"（{acceptable_top1_hits / total:.1%}）"
    )
    print(
        f"严格引用Top3：{strict_top3_hits}/{total}"
        f"（{strict_top3_hits / total:.1%}）"
    )
    print(
        f"可接受引用Top3：{acceptable_top3_hits}/{total}"
        f"（{acceptable_top3_hits / total:.1%}）"
    )
    print(
        "未检测到引用："
        + ("、".join(no_citation) if no_citation else "无")
    )
    print(f"明细结果：{output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
import argparse
import json
import re
from pathlib import Path

from dotenv import dotenv_values

from ragflow_client import RAGFlowClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"


def find_latest_result():
    candidates = sorted(
        RESULTS_DIR.glob("batch_eval_50_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not candidates:
        raise RuntimeError("未找到50题批测JSON结果")

    return candidates[0]


def extract_citation_ids(answer):
    citation_ids = []

    for value in re.findall(
        r"\[[^\]]*?ID:(\d+)[^\]]*\]",
        answer or "",
    ):
        citation_id = int(value)

        if citation_id not in citation_ids:
            citation_ids.append(citation_id)

    return citation_ids


def build_evidence(record):
    references = record.get("references", [])
    citation_ids = extract_citation_ids(
        record.get("answer", "")
    )

    evidence_parts = []

    for citation_id in citation_ids:
        if citation_id >= len(references):
            continue

        reference = references[citation_id]
        content = re.sub(
            r"\s+",
            " ",
            reference.get("content", ""),
        ).strip()

        evidence_parts.append(
            "\n".join(
                [
                    f"[ID:{citation_id}]",
                    (
                        "文档："
                        + reference.get(
                            "document_name",
                            "",
                        )
                    ),
                    f"内容：{content[:1800]}",
                ]
            )
        )

    return "\n\n".join(evidence_parts)


def build_prompt(record):
    return "\n".join(
        [
            "请评测以下RAG回答。",
            "",
            "【用户问题】",
            record["question"],
            "",
            "【人工标准答案要点】",
            record["reference_answer"],
            "",
            "【待评测回答】",
            record["answer"],
            "",
            "【回答实际引用的证据】",
            build_evidence(record),
        ]
    )


def parse_judge_json(text):
    cleaned = text.strip()
    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("裁判结果中没有JSON对象")

    result = json.loads(cleaned[start : end + 1])

    if result.get("citation_correct") not in (0, 1):
        raise ValueError("citation_correct取值无效")

    if result.get("answer_accuracy") not in (0, 1, 2):
        raise ValueError("answer_accuracy取值无效")

    if result.get("hallucination") not in (0, 1):
        raise ValueError("hallucination取值无效")

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--question-id",
        default="Q044",
        help="要测试的问题ID，默认Q044",
    )
    args = parser.parse_args()

    result_path = find_latest_result()

    with result_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        payload = json.load(file)

    record = next(
        (
            item
            for item in payload["results"]
            if item["question_id"] == args.question_id
        ),
        None,
    )

    if not record:
        raise RuntimeError(
            f"没有找到问题：{args.question_id}"
        )

    env = dotenv_values(PROJECT_ROOT / ".env")
    judge_name = env.get("RAGFLOW_JUDGE_CHAT_NAME")

    if not judge_name:
        raise RuntimeError(
            ".env缺少RAGFLOW_JUDGE_CHAT_NAME"
        )

    judge_client = RAGFlowClient(
        chat_name=judge_name
    )

    response = judge_client.ask(
        build_prompt(record)
    )
    raw_answer = response["answer"]
    score = parse_judge_json(raw_answer)

    print("=" * 60)
    print(f"问题ID：{record['question_id']}")
    print(f"问题：{record['question']}")
    print("裁判原始输出：")
    print(raw_answer)
    print("-" * 60)
    print("解析结果：")
    print(
        json.dumps(
            score,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

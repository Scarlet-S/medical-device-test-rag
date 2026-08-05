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


def extract_match_terms(text):
    normalized = re.sub(r"\s+", " ", text or "").lower()
    terms = set(
        re.findall(
            r"[a-z0-9][a-z0-9_.\-/]{2,}",
            normalized,
        )
    )

    for sequence in re.findall(r"[\u4e00-\u9fff]{3,}", normalized):
        terms.update(
            sequence[index : index + 3]
            for index in range(len(sequence) - 2)
        )

    terms.update(
        quote.strip().lower()
        for quote in re.findall(
            r"[“\"]([^”\"]{6,120})[”\"]",
            normalized,
        )
    )

    return terms


def select_evidence_excerpt(
    content,
    query,
    window_size=2200,
    max_windows=2,
):
    if len(content) <= window_size * max_windows:
        return content

    terms = extract_match_terms(query)
    step = window_size // 2
    starts = list(range(0, len(content), step))
    last_start = max(0, len(content) - window_size)

    if last_start not in starts:
        starts.append(last_start)

    candidates = []

    for start in starts:
        window = content[start : start + window_size]
        lowered = window.lower()
        score = sum(
            min(len(term), 12)
            for term in terms
            if term in lowered
        )
        candidates.append((score, start, window))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    selected = []

    for score, start, window in candidates:
        if selected and score <= 0:
            break

        if any(
            abs(start - selected_start) < window_size
            for _, selected_start, _ in selected
        ):
            continue

        selected.append((score, start, window))

        if len(selected) == max_windows:
            break

    if not selected:
        selected = [(0, 0, content[:window_size])]

    selected.sort(key=lambda item: item[1])
    excerpts = []

    for _, start, window in selected:
        prefix = "……" if start > 0 else ""
        suffix = (
            "……"
            if start + len(window) < len(content)
            else ""
        )
        excerpts.append(prefix + window + suffix)

    return "\n\n".join(excerpts)


def build_evidence(record):
    references = record.get("references", [])
    citation_ids = extract_citation_ids(
        record.get("answer", "")
    )
    evidence_ids = citation_ids + [
        reference_id
        for reference_id in range(len(references))
        if reference_id not in citation_ids
    ]
    query = "\n".join(
        [
            record.get("question", ""),
            record.get("reference_answer", ""),
            record.get("answer", ""),
        ]
    )

    evidence_parts = []

    for citation_id in evidence_ids:
        if citation_id >= len(references):
            continue

        reference = references[citation_id]
        is_explicitly_cited = citation_id in citation_ids
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
                    (
                        "回答显式引用："
                        + (
                            "是"
                            if is_explicitly_cited
                            else "否"
                        )
                    ),
                    (
                        "内容："
                        + select_evidence_excerpt(
                            content,
                            query,
                            window_size=(
                                1800
                                if is_explicitly_cited
                                else 900
                            ),
                            max_windows=(
                                2
                                if is_explicitly_cited
                                else 1
                            ),
                        )
                    ),
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
            "【RAG系统实际返回的引用证据】",
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

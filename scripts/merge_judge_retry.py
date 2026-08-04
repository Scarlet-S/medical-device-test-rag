import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "results"


def parse_args():
    parser = argparse.ArgumentParser(
        description="将成功的裁判补测记录合并到已有裁判结果中，不调用模型。"
    )
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument(
        "--retry",
        type=Path,
        required=True,
        nargs="+",
        help="一个或多个裁判补测JSON，按给定顺序覆盖同一题。",
    )
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--source-result",
        type=Path,
        help="可选：合并后的裁判结果所对应的检索结果JSON。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    return parser.parse_args()


def load_payload(path):
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError(f"不是有效的裁判结果JSON：{path}")
    return payload


def ratio(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def build_summary(results):
    total = len(results)
    successful = sum(row.get("status") == "success" for row in results)
    failed = total - successful
    citation_correct = sum(
        int(row.get("citation_correct") or 0)
        for row in results
        if row.get("status") == "success"
    )
    answer_accuracy_points = sum(
        int(row.get("answer_accuracy") or 0)
        for row in results
        if row.get("status") == "success"
    )
    answer_accuracy_max_points = total * 2
    hallucinations = sum(
        int(row.get("hallucination") or 0)
        for row in results
        if row.get("status") == "success"
    )
    return {
        "total": total,
        "successful": successful,
        "failed": failed,
        "citation_correct": citation_correct,
        "citation_correct_rate": ratio(citation_correct, total),
        "answer_accuracy_points": answer_accuracy_points,
        "answer_accuracy_max_points": answer_accuracy_max_points,
        "answer_accuracy_rate": ratio(
            answer_accuracy_points,
            answer_accuracy_max_points,
        ),
        "hallucinations": hallucinations,
        "hallucination_rate": ratio(hallucinations, total),
    }


def write_csv(path, results):
    fieldnames = []
    for row in results:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)


def main():
    args = parse_args()
    base = load_payload(args.base)
    results = [dict(row) for row in base["results"]]
    positions = {
        row.get("question_id"): index
        for index, row in enumerate(results)
        if row.get("question_id")
    }

    replaced = []
    for retry_path in args.retry:
        retry = load_payload(retry_path)
        for row in retry["results"]:
            question_id = row.get("question_id")
            if question_id not in positions:
                raise KeyError(
                    f"补测题目{question_id!r}不在基础裁判结果中：{retry_path}"
                )
            if row.get("status") != "success":
                print(f"跳过失败补测：{question_id}")
                continue
            results[positions[question_id]] = dict(row)
            replaced.append(question_id)

    if not replaced:
        raise RuntimeError("没有找到可合并的成功裁判补测记录")

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = build_summary(results)
    source_result = (
        str(args.source_result.resolve())
        if args.source_result
        else base.get("source_result")
    )
    payload = {
        "generated_at": generated_at,
        "source_result": source_result,
        "summary": summary,
        "results": results,
        "merge": {
            "base": str(args.base.resolve()),
            "retries": [str(path.resolve()) for path in args.retry],
            "replaced_question_ids": list(dict.fromkeys(replaced)),
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"judge_eval_{summary['total']}_{args.label}_{timestamp}"
    json_path = args.output_dir / f"{stem}.json"
    csv_path = args.output_dir / f"{stem}.csv"
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    write_csv(csv_path, results)

    print("=" * 60)
    print(f"总题数：{summary['total']}")
    print(f"成功：{summary['successful']}")
    print(f"失败：{summary['failed']}")
    print(
        f"引用正确：{summary['citation_correct']}/{summary['total']}"
    )
    print(
        "回答准确度："
        f"{summary['answer_accuracy_points']}/"
        f"{summary['answer_accuracy_max_points']}"
    )
    print(f"幻觉：{summary['hallucinations']}/{summary['total']}")
    print(f"替换题目：{'、'.join(dict.fromkeys(replaced))}")
    print(f"JSON结果：{json_path.resolve()}")
    print(f"CSV结果：{csv_path.resolve()}")


if __name__ == "__main__":
    main()

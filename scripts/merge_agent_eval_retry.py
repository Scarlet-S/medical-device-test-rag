import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT_PATH = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))

from scripts.run_agent_eval import PROJECT_ROOT, save_results


def load_run(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("results"), list):
        raise RuntimeError(f"Agent评测结果缺少results数组：{path}")
    return payload


def merge_records(
    base_records: list[dict[str, Any]],
    retry_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    retry_by_id = {
        str(record.get("case_id") or "").upper(): record
        for record in retry_records
        if record.get("case_id")
    }
    merged = []
    replaced = []
    for base in base_records:
        case_id = str(base.get("case_id") or "").upper()
        retry = retry_by_id.get(case_id)
        if retry and retry.get("status") == "success":
            if retry.get("question") != base.get("question"):
                raise RuntimeError(f"补测题目内容不一致：{case_id}")
            if retry.get("expected_agent") != base.get("expected_agent"):
                raise RuntimeError(f"补测预期Agent不一致：{case_id}")
            merged.append(retry)
            replaced.append(case_id)
        else:
            merged.append(base)
    return merged, replaced


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="用成功的Agent补测记录替换基础评测中的同题记录。"
    )
    parser.add_argument("--base", required=True)
    parser.add_argument("--retry", required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    base_path = resolve_path(args.base)
    retry_path = resolve_path(args.retry)
    base = load_run(base_path)
    retry = load_run(retry_path)
    merged, replaced = merge_records(base["results"], retry["results"])
    if not replaced:
        raise RuntimeError("没有找到可由成功补测记录替换的题目")

    source_path = Path(base.get("source_dataset") or base_path)
    json_path, csv_path, summary = save_results(
        merged,
        source_path,
        args.label,
    )
    print("=" * 60)
    print(f"合并题数：{summary['total']}")
    print(f"成功：{summary['successful']}")
    print(f"失败：{summary['failed']}")
    print(f"API执行成功率：{summary['execution_success_rate']:.1%}")
    print(f"端到端路由准确率：{summary['routing_end_to_end_accuracy']:.1%}")
    print(
        "端到端工具召回率："
        f"{summary['required_tool_end_to_end_recall']:.1%}"
    )
    print(f"任务完成率：{summary['task_completion_rate']:.1%}")
    print(f"替换题目：{','.join(replaced)}")
    print(f"JSON结果：{json_path}")
    print(f"CSV结果：{csv_path}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

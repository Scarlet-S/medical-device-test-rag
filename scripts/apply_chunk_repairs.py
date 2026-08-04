import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(r"D:\Tools\CodeTools\Projects\medical-device-test-rag")
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ingest_single_document import RAGFlowIngestionClient  # noqa: E402


TRANSIENT_ERROR_MARKERS = (
    "SSLError",
    "ReadTimeout",
    "ConnectionError",
    "Max retries exceeded",
    "timed out",
    "UNEXPECTED_EOF_WHILE_READING",
)


def patch_with_transient_retry(
    client,
    path,
    payload,
    *,
    attempts=4,
):
    """Retry idempotent PATCH calls only for transient network failures."""
    for attempt in range(1, attempts + 1):
        try:
            return client.request(
                "PATCH",
                path,
                json=payload,
            )
        except Exception as exc:
            message = repr(exc)
            is_transient = any(
                marker.casefold() in message.casefold()
                for marker in TRANSIENT_ERROR_MARKERS
            )
            if not is_transient or attempt == attempts:
                raise
            wait_seconds = min(2 ** attempt, 10)
            print(
                f"  临时网络错误，第{attempt}/{attempts}次失败；"
                f"{wait_seconds}秒后重试……",
                flush=True,
            )
            time.sleep(wait_seconds)


def stable_unique(values):
    result = []
    seen = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def load_config(path):
    return json.loads(path.read_text(encoding="utf-8"))


def find_document(client, dataset_id, document_id, document_code):
    documents = client.list_documents(dataset_id)
    matches = [
        item
        for item in documents
        if item.get("id") == document_id
        or item.get("name", "").startswith(document_code)
    ]
    if not matches:
        raise LookupError(
            f"未找到文档：{document_code}（{document_id}）"
        )
    exact = [item for item in matches if item.get("id") == document_id]
    return exact[0] if exact else matches[0]


def get_chunk(chunks, chunk_id):
    for chunk in chunks:
        if chunk.get("id") == chunk_id:
            return chunk
    raise LookupError(f"未找到切片：{chunk_id}")


def chunk_content(chunk):
    return chunk.get("content") or chunk.get("content_with_weight") or ""


def addition_content(addition):
    aliases = stable_unique(addition.get("retrieval_aliases_en", []))
    if not aliases:
        return addition["content"]
    alias_block = "\n".join(f"- {alias}" for alias in aliases)
    return (
        f"{addition['content'].rstrip()}"
        "\n\n## Retrieval aliases (English)\n"
        f"{alias_block}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT
        / "evaluation"
        / "config"
        / "retrieval_chunk_repairs_v1.json",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--save-backup",
        action="store_true",
        help="在不写入RAGFlow时也保存当前切片快照。",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=PROJECT_ROOT / "evaluation" / "results",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    client = RAGFlowIngestionClient()
    dataset = client.find_dataset(config["dataset_name"])
    dataset_id = dataset["id"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "dataset": {"id": dataset_id, "name": dataset["name"]},
        "config_version": config["version"],
        "patches": [],
        "additions": [],
    }

    chat_adjustment = config.get("chat_adjustment")
    if chat_adjustment:
        chat_data = client.request(
            "GET",
            "/api/v1/chats",
            params={"name": chat_adjustment["chat_name"]},
        )
        chats = (
            chat_data.get("chats", [])
            if isinstance(chat_data, dict)
            else chat_data
        )
        exact_chats = [
            chat
            for chat in chats
            if chat.get("name", "").casefold()
            == chat_adjustment["chat_name"].casefold()
        ]
        if len(exact_chats) != 1:
            raise LookupError(
                f"无法唯一定位聊天助手：{chat_adjustment['chat_name']}"
            )
        chat = exact_chats[0]
        old_prompt_config = chat.get("prompt_config", {})
        new_prompt_config = chat_adjustment["prompt_config"]
        backup["chat_adjustment"] = {
            "chat_id": chat["id"],
            "chat_name": chat["name"],
            "old_prompt_config": old_prompt_config,
            "patch_prompt_config": new_prompt_config,
            "reason": chat_adjustment.get("reason", ""),
        }
        old_cross_languages = old_prompt_config.get(
            "cross_languages",
            [],
        )
        new_cross_languages = new_prompt_config.get(
            "cross_languages",
            old_cross_languages,
        )
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(
            f"[{mode}] CHAT cross_languages "
            f"{old_cross_languages}->{new_cross_languages}"
        )
        if args.apply and old_cross_languages != new_cross_languages:
            patch_with_transient_retry(
                client,
                f"/api/v1/chats/{chat['id']}",
                {"prompt_config": new_prompt_config},
            )

    document_cache = {}
    chunk_cache = {}

    for repair in config["patches"]:
        document_id = repair["document_id"]
        document = document_cache.get(document_id)
        if document is None:
            document = find_document(
                client,
                dataset_id,
                document_id,
                repair["document_code"],
            )
            document_cache[document_id] = document
            chunk_cache[document_id] = client.list_all_chunks(
                dataset_id,
                document["id"],
            )

        chunk = get_chunk(
            chunk_cache[document_id],
            repair["chunk_id"],
        )
        old_content = chunk_content(chunk)
        new_content = repair.get("replacement_content", old_content)
        old_questions = stable_unique(chunk.get("questions", []))
        old_keywords = stable_unique(
            chunk.get("important_keywords", [])
        )
        new_questions = stable_unique(
            old_questions
            + repair["questions"]
            + repair.get("retrieval_aliases_en", [])
        )
        new_keywords = stable_unique(
            old_keywords + repair["important_keywords"]
        )

        backup["patches"].append(
            {
                "document_code": repair["document_code"],
                "document_id": document["id"],
                "document_name": document["name"],
                "chunk_id": chunk["id"],
                "question_ids": repair["question_ids"],
                "content": old_content,
                "new_content": new_content,
                "questions": old_questions,
                "important_keywords": old_keywords,
                "new_questions": new_questions,
                "new_important_keywords": new_keywords,
            }
        )

        mode = "APPLY" if args.apply else "DRY-RUN"
        print(
            f"[{mode}] {','.join(repair['question_ids'])} "
            f"{repair['document_code']} chunk={chunk['id']} "
            f"content={'changed' if old_content != new_content else 'unchanged'} "
            f"questions {len(old_questions)}->{len(new_questions)} "
            f"keywords {len(old_keywords)}->{len(new_keywords)}"
        )
        needs_patch = (
            old_content != new_content
            or old_questions != new_questions
            or old_keywords != new_keywords
        )
        if args.apply and needs_patch:
            patch_with_transient_retry(
                client,
                (
                    f"/api/v1/datasets/{dataset_id}/documents/"
                    f"{document['id']}/chunks/{chunk['id']}"
                ),
                {
                    "content": new_content,
                    "questions": new_questions,
                    "important_keywords": new_keywords,
                },
            )
        elif args.apply:
            print("  已是目标状态，跳过写入。", flush=True)

    for addition in config["additions"]:
        document = find_document(
            client,
            dataset_id,
            addition["document_id"],
            addition["document_code"],
        )
        chunks = client.list_all_chunks(dataset_id, document["id"])
        desired_content = addition_content(addition)
        base_content = addition["content"].strip()
        desired_questions = stable_unique(
            addition["questions"]
            + addition.get("retrieval_aliases_en", [])
        )
        existing = [
            chunk
            for chunk in chunks
            if chunk_content(chunk).strip()
            in {base_content, desired_content.strip()}
        ]
        if len(existing) > 1:
            raise RuntimeError(
                f"{addition['question_ids']}存在多个聚焦切片，"
                "请先人工确认重复项。"
            )
        old_chunk = existing[0] if existing else None
        old_questions = stable_unique(
            old_chunk.get("questions", []) if old_chunk else []
        )
        old_keywords = stable_unique(
            old_chunk.get("important_keywords", [])
            if old_chunk
            else []
        )
        merged_questions = stable_unique(
            old_questions + desired_questions
        )
        merged_keywords = stable_unique(
            old_keywords + addition["important_keywords"]
        )
        needs_update = bool(
            old_chunk
            and (
                chunk_content(old_chunk).strip()
                != desired_content.strip()
                or old_questions != merged_questions
                or old_keywords != merged_keywords
            )
        )
        backup["additions"].append(
            {
                **addition,
                "document_name": document["name"],
                "already_exists": bool(existing),
                "existing_chunk_ids": [
                    chunk.get("id") for chunk in existing
                ],
                "old_content": (
                    chunk_content(old_chunk) if old_chunk else None
                ),
                "old_questions": old_questions,
                "old_important_keywords": old_keywords,
            }
        )

        mode = "APPLY" if args.apply else "DRY-RUN"
        state = (
            "update"
            if needs_update
            else ("exists" if existing else "new")
        )
        print(
            f"[{mode}] {','.join(addition['question_ids'])} "
            f"{addition['document_code']} focused-chunk={state}"
        )
        if args.apply and not existing:
            client.request(
                "POST",
                (
                    f"/api/v1/datasets/{dataset_id}/documents/"
                    f"{document['id']}/chunks"
                ),
                json={
                    "content": desired_content,
                    "questions": desired_questions,
                    "important_keywords": addition[
                        "important_keywords"
                    ],
                },
            )
        elif args.apply and needs_update:
            patch_with_transient_retry(
                client,
                (
                    f"/api/v1/datasets/{dataset_id}/documents/"
                    f"{document['id']}/chunks/{old_chunk['id']}"
                ),
                {
                    "content": desired_content,
                    "questions": merged_questions,
                    "important_keywords": merged_keywords,
                },
            )

    if args.apply or args.save_backup:
        args.backup_dir.mkdir(parents=True, exist_ok=True)
        destination = (
            args.backup_dir
            / f"chunk_repair_backup_v1_{timestamp}.json"
        )
        destination.write_text(
            json.dumps(backup, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("=" * 60)
        print(f"备份：{destination}")
    if args.apply:
        print(
            f"完成：更新{len(config['patches'])}个现有切片，"
            f"检查/新增{len(config['additions'])}个聚焦切片。"
        )
    else:
        print("=" * 60)
        print("仅完成预检查，未修改RAGFlow。使用 --apply 才会写入。")


if __name__ == "__main__":
    main()

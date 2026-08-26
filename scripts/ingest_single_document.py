import argparse
import json
import mimetypes
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
RUN_STATES = {
    "0": "UNSTART",
    "1": "RUNNING",
    "2": "CANCEL",
    "3": "DONE",
    "4": "FAIL",
    "UNSTART": "UNSTART",
    "RUNNING": "RUNNING",
    "CANCEL": "CANCEL",
    "DONE": "DONE",
    "FAIL": "FAIL",
}


class RAGFlowIngestionClient:
    """Small RAGFlow HTTP client shared by ingestion and repair scripts."""

    def __init__(self):
        load_dotenv(PROJECT_ROOT / ".env")
        self.base_url = os.getenv("RAGFLOW_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("RAGFLOW_API_KEY", "")
        self.chat_name = os.getenv("RAGFLOW_CHAT_NAME", "").strip()
        self.timeout = int(os.getenv("RAGFLOW_TIMEOUT_SECONDS", "120"))

        missing = [
            name
            for name, value in {
                "RAGFLOW_BASE_URL": self.base_url,
                "RAGFLOW_API_KEY": self.api_key,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f".env 缺少配置：{', '.join(missing)}")

        self.http = requests.Session()
        self.http.headers.update(
            {"Authorization": f"Bearer {self.api_key}"}
        )

    def request(self, method, path, **kwargs):
        timeout = kwargs.pop("timeout", self.timeout)
        method = method.upper()
        attempts = 3 if method == "GET" else 1
        for attempt in range(1, attempts + 1):
            try:
                response = self.http.request(
                    method,
                    f"{self.base_url}{path}",
                    timeout=timeout,
                    **kwargs,
                )
                break
            except (requests.ConnectionError, requests.Timeout):
                if attempt >= attempts:
                    raise
                time.sleep(min(attempt, 2))
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(
                payload.get("message", f"RAGFlow API 请求失败：{path}")
            )
        return payload.get("data")

    def infer_dataset_name(self):
        configured = os.getenv("RAGFLOW_DATASET_NAME", "").strip()
        if configured:
            return configured
        if not self.chat_name:
            return ""

        data = self.request(
            "GET",
            "/api/v1/chats",
            params={"name": self.chat_name},
        )
        chats = data.get("chats", []) if isinstance(data, dict) else data
        if not chats:
            return ""
        names = chats[0].get("kb_names", [])
        return names[0] if len(names) == 1 else ""

    def find_dataset(self, dataset_name):
        data = self.request(
            "GET",
            "/api/v1/datasets",
            params={"name": dataset_name, "page_size": 100},
        )
        datasets = data.get("datasets", []) if isinstance(data, dict) else data
        exact = [
            item
            for item in datasets
            if item.get("name", "").casefold() == dataset_name.casefold()
        ]
        if not exact:
            raise RuntimeError(f"没有找到知识库：{dataset_name}")
        if len(exact) > 1:
            raise RuntimeError(
                f"找到多个同名知识库，请先在RAGFlow中确认：{dataset_name}"
            )
        return exact[0]

    def list_documents(self, dataset_id):
        documents = []
        page = 1
        page_size = 100
        while True:
            data = self.request(
                "GET",
                f"/api/v1/datasets/{dataset_id}/documents",
                params={"page": page, "page_size": page_size},
            )
            page_docs = data.get("docs", []) if isinstance(data, dict) else data
            page_docs = page_docs or []
            documents.extend(page_docs)
            total = data.get("total") if isinstance(data, dict) else None
            if not page_docs:
                break
            if total is not None and len(documents) >= int(total):
                break
            if len(page_docs) < page_size:
                break
            page += 1
            if page > 10000:
                raise RuntimeError("文档分页超过10000页，已停止以避免无限循环")
        return documents

    def upload_document(self, dataset_id, file_path, upload_name=None):
        upload_name = upload_name or file_path.name
        mime_type = mimetypes.guess_type(upload_name)[0]
        mime_type = mime_type or "application/octet-stream"
        with file_path.open("rb") as source:
            data = self.request(
                "POST",
                f"/api/v1/datasets/{dataset_id}/documents",
                files={"file": (upload_name, source, mime_type)},
                timeout=max(self.timeout, 300),
            )
        documents = data.get("docs", []) if isinstance(data, dict) else data
        if not documents:
            raise RuntimeError("RAGFlow上传成功，但没有返回文档信息")
        return documents[0]

    def start_parsing(self, dataset_id, document_id):
        self.request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/chunks",
            json={"document_ids": [document_id]},
        )

    def update_chunk_method(self, dataset_id, document_id, chunk_method):
        return self.request(
            "PATCH",
            f"/api/v1/datasets/{dataset_id}/documents/{document_id}",
            json={"chunk_method": chunk_method},
        )

    def get_document(self, dataset_id, document_id):
        data = self.request(
            "GET",
            f"/api/v1/datasets/{dataset_id}/documents",
            params={"id": document_id, "page": 1, "page_size": 10},
        )
        documents = data.get("docs", []) if isinstance(data, dict) else data
        if not documents:
            raise RuntimeError(f"无法读取文档状态：{document_id}")
        return documents[0]

    def wait_for_document(
        self,
        dataset_id,
        document_id,
        wait_seconds=1800,
        poll_seconds=5,
        progress_callback=None,
    ):
        deadline = time.monotonic() + wait_seconds
        while True:
            document = self.get_document(dataset_id, document_id)
            state = normalized_state(document.get("run", ""))
            if progress_callback:
                progress_callback(document, state)
            if state == "DONE":
                return document
            if state in {"FAIL", "CANCEL"}:
                raise RuntimeError(
                    f"解析状态：{state}；"
                    f"信息：{document.get('progress_msg', '')}"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"解析超过{wait_seconds}秒，文档可能仍在RAGFlow后台运行"
                )
            time.sleep(max(poll_seconds, 1))

    def list_all_chunks(self, dataset_id, document_id):
        chunks = []
        page = 1
        page_size = 100
        while True:
            data = self.request(
                "GET",
                (
                    f"/api/v1/datasets/{dataset_id}/documents/"
                    f"{document_id}/chunks"
                ),
                params={"page": page, "page_size": page_size},
            )
            page_chunks = data.get("chunks", []) if isinstance(data, dict) else data
            page_chunks = page_chunks or []
            chunks.extend(page_chunks)
            total = data.get("total") if isinstance(data, dict) else None
            if not page_chunks:
                break
            if total is not None and len(chunks) >= int(total):
                break
            if len(page_chunks) < page_size:
                break
            page += 1
            if page > 10000:
                raise RuntimeError("切片分页超过10000页，已停止以避免无限循环")
        return chunks

    def create_chunk(
        self,
        dataset_id,
        document_id,
        content,
        questions=None,
        important_keywords=None,
    ):
        return self.request(
            "POST",
            (
                f"/api/v1/datasets/{dataset_id}/documents/"
                f"{document_id}/chunks"
            ),
            json={
                "content": content,
                "questions": questions or [],
                "important_keywords": important_keywords or [],
            },
            timeout=max(self.timeout, 300),
        )


def normalized_state(value):
    return RUN_STATES.get(str(value).upper(), str(value).upper())


def chunk_text(chunk):
    value = chunk.get("content")
    if value is None:
        value = chunk.get("content_with_weight", "")
    return value if isinstance(value, str) else str(value or "")


def audit_chunks(chunks):
    texts = [chunk_text(chunk) for chunk in chunks]
    lengths = [len(text.strip()) for text in texts]
    suspicious_tokens = ("\ufffd", "锟斤拷", "鏂囧瓧", "缂哄皯")
    return {
        "chunk_count": len(chunks),
        "empty_chunk_count": sum(not text.strip() for text in texts),
        "mojibake_chunk_count": sum(
            any(token in text for token in suspicious_tokens)
            for text in texts
        ),
        "very_short_chunk_count": sum(0 < length < 40 for length in lengths),
        "very_long_chunk_count": sum(length > 6000 for length in lengths),
        "length_min": min(lengths) if lengths else 0,
        "length_median": statistics.median(lengths) if lengths else 0,
        "length_max": max(lengths) if lengths else 0,
        "previews": [
            {
                "index": index,
                "chunk_id": chunk.get("id", ""),
                "length": len(text.strip()),
                "preview": " ".join(text.split())[:240],
            }
            for index, (chunk, text) in enumerate(
                zip(chunks[:5], texts[:5]), start=1
            )
        ],
    }


def save_qa_report(dataset, document, audit, output_path=None):
    destination = output_path
    if destination is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        document_code = document.get("name", "document").split("_", 1)[0]
        destination = (
            DEFAULT_RESULTS_DIR
            / f"ingestion_qa_{document_code}_{timestamp}.json"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "dataset": {
            "id": dataset.get("id", ""),
            "name": dataset.get("name", ""),
            "chunk_method": dataset.get("chunk_method", ""),
        },
        "document": {
            "id": document.get("id", ""),
            "name": document.get("name", ""),
            "run": normalized_state(document.get("run", "")),
            "progress": document.get("progress"),
            "progress_msg": document.get("progress_msg", ""),
            "chunk_count": document.get("chunk_count"),
        },
        "audit": audit,
    }
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return destination


def parse_args():
    parser = argparse.ArgumentParser(
        description="安全上传、解析并检查一个RAGFlow文档。"
    )
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument(
        "--dataset-name",
        help="目标知识库名称；缺省时读取.env或助手关联知识库。",
    )
    parser.add_argument(
        "--use-existing",
        action="store_true",
        help="同名文档已存在时复用它；默认停止以避免重复上传。",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="复用文档处于失败状态时重新启动解析。",
    )
    parser.add_argument(
        "--chunk-method",
        choices=[
            "naive",
            "manual",
            "qa",
            "table",
            "paper",
            "book",
            "laws",
            "presentation",
            "picture",
            "one",
            "email",
            "tag",
        ],
        help="为该文档指定切片方法；仅在明确传入时更新。",
    )
    parser.add_argument("--wait-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--qa-output", type=Path)
    return parser.parse_args()


def main():
    args = parse_args()
    file_path = args.file.expanduser().resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"文件不存在：{file_path}")

    client = RAGFlowIngestionClient()
    dataset_name = (args.dataset_name or "").strip() or client.infer_dataset_name()
    if not dataset_name:
        raise RuntimeError(
            "无法确定目标知识库。请使用--dataset-name指定，"
            "或在.env中配置RAGFLOW_DATASET_NAME。"
        )

    dataset = client.find_dataset(dataset_name)
    print(f"知识库：{dataset['name']}")
    print(f"本地文件：{file_path}")

    existing = [
        document
        for document in client.list_documents(dataset["id"])
        if document.get("name", "").casefold() == file_path.name.casefold()
    ]
    if existing and not args.use_existing:
        document = existing[0]
        print(
            "检测到同名文档，未重复上传："
            f"{document.get('name')}（ID：{document.get('id')}）"
        )
        print("确认要复用该文档时，请增加--use-existing。")
        return 2

    if existing:
        document = existing[0]
        print(f"复用已有文档：{document.get('id')}")
    else:
        print("正在上传文档……")
        document = client.upload_document(dataset["id"], file_path)
        print(f"上传完成，文档ID：{document.get('id')}")

    current_method = (
        document.get("chunk_method") or document.get("parser_id") or ""
    ).lower()
    if args.chunk_method and current_method != args.chunk_method:
        document = client.update_chunk_method(
            dataset["id"], document["id"], args.chunk_method
        )

    state = normalized_state(document.get("run", ""))
    if state == "UNSTART":
        print("正在启动解析和切片……")
        client.start_parsing(dataset["id"], document["id"])
    elif state == "FAIL" and args.retry_failed:
        print("正在重新启动失败文档的解析和切片……")
        client.start_parsing(dataset["id"], document["id"])
    elif state == "DONE":
        print("文档已经解析完成，直接执行切片质量检查。")
    elif state == "RUNNING":
        print("文档正在解析，继续等待。")
    else:
        raise RuntimeError(f"文档当前状态为{state}，脚本不会自动重新解析。")

    last_message = None

    def show_progress(current, state_name):
        nonlocal last_message
        message = (
            f"状态：{state_name}｜进度：{current.get('progress')}"
            f"｜切片：{current.get('chunk_count', 0)}"
        )
        if message != last_message:
            print(message)
            last_message = message

    document = client.wait_for_document(
        dataset["id"],
        document["id"],
        wait_seconds=args.wait_seconds,
        poll_seconds=args.poll_seconds,
        progress_callback=show_progress,
    )
    chunks = client.list_all_chunks(dataset["id"], document["id"])
    audit = audit_chunks(chunks)
    report_path = save_qa_report(dataset, document, audit, args.qa_output)

    print("=" * 60)
    print(f"解析完成：{document.get('name')}")
    print(f"切片数量：{audit['chunk_count']}")
    print(f"空切片：{audit['empty_chunk_count']}")
    print(f"疑似乱码切片：{audit['mojibake_chunk_count']}")
    print(
        "字符长度（最小/中位数/最大）："
        f"{audit['length_min']}/{audit['length_median']}/{audit['length_max']}"
    )
    print(f"质量报告：{report_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.RequestException as exc:
        print(f"RAGFlow网络/API请求失败：{exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        sys.exit(1)

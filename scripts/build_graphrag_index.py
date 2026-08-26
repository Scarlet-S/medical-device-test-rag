"""Build the online GraphRAG pilot index from real RAGFlow chunks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.graphrag import build_graph_dataset_from_chunks
from scripts.ingest_single_document import RAGFlowIngestionClient


DEFAULT_SCHEMA = (
    PROJECT_ROOT / "evaluation" / "graphrag" / "medical_device_graph_v1.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "evaluation" / "graphrag" / "ragflow_chunk_graph_v1.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read every parsed RAGFlow chunk and build a traceable entity "
            "co-occurrence graph. This does not modify the knowledge base."
        )
    )
    parser.add_argument("--dataset-name", default="")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--document-prefix", default="")
    return parser.parse_args()


def document_code(name: str) -> str:
    match = re.match(r"([A-Za-z]+\d+)", name.strip())
    return match.group(1).upper() if match else ""


def main() -> int:
    args = parse_args()
    client = RAGFlowIngestionClient()
    dataset_name = args.dataset_name.strip() or client.infer_dataset_name()
    if not dataset_name:
        raise RuntimeError(
            "无法确定知识库名称，请配置RAGFLOW_DATASET_NAME或传入--dataset-name"
        )
    dataset = client.find_dataset(dataset_name)
    documents = client.list_documents(dataset["id"])
    if args.document_prefix:
        documents = [
            item
            for item in documents
            if str(item.get("name") or "").startswith(args.document_prefix)
        ]

    chunk_records = []
    for index, document in enumerate(documents, start=1):
        name = str(document.get("name") or "")
        chunks = client.list_all_chunks(dataset["id"], document["id"])
        for chunk in chunks:
            item = dict(chunk)
            item["document_name"] = name
            item["document_code"] = document_code(name)
            raw_title = chunk.get("title") or chunk.get("important_keywords")
            if isinstance(raw_title, list):
                raw_title = "｜".join(str(value) for value in raw_title)
            item["title"] = str(raw_title or name)
            chunk_records.append(item)
        print(f"[{index}/{len(documents)}] {name}｜切片：{len(chunks)}")

    with args.schema.open("r", encoding="utf-8-sig") as handle:
        schema = json.load(handle)
    graph = build_graph_dataset_from_chunks(
        chunk_records,
        schema,
        name=f"{dataset_name}-ragflow-chunk-graph-v1",
    )
    graph["generated_at"] = datetime.now(timezone.utc).isoformat()
    graph["source_dataset"] = {
        "id": str(dataset["id"]),
        "name": dataset_name,
        "document_count": len(documents),
        "chunk_count": len(chunk_records),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("=" * 60)
    print(f"文档数：{len(documents)}")
    print(f"切片数：{len(chunk_records)}")
    print(f"实体数：{len(graph['nodes'])}")
    print(f"可追溯关系数：{len(graph['relations'])}")
    print(f"图索引：{args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

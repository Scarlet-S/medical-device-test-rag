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
    parser.add_argument(
        "--dataset-name",
        action="append",
        default=[],
        help="可重复传入多个知识库名称；未传入时从聊天助手推断主知识库。",
    )
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--document-prefix", default="")
    parser.add_argument(
        "--max-total-chunks",
        type=int,
        default=0,
        help="跨知识库最多纳入的真实切片数；0表示不限制。",
    )
    parser.add_argument(
        "--max-evidence-per-pair",
        type=int,
        default=0,
        help="每个实体对最多保留的共现证据数；0表示全部保留。",
    )
    return parser.parse_args()


def document_code(name: str) -> str:
    match = re.match(
        r"([A-Za-z]+(?:[_-]?[A-Za-z]+)*[_-]?\d+)", name.strip()
    )
    return match.group(1).upper() if match else ""


def main() -> int:
    args = parse_args()
    client = RAGFlowIngestionClient()
    dataset_names = [name.strip() for name in args.dataset_name if name.strip()]
    if not dataset_names:
        inferred = client.infer_dataset_name()
        dataset_names = [inferred] if inferred else []
    if not dataset_names:
        raise RuntimeError(
            "无法确定知识库名称，请配置RAGFLOW_DATASET_NAME或传入--dataset-name"
        )

    chunk_records = []
    source_datasets = []
    stop = False
    for dataset_name in dataset_names:
        dataset = client.find_dataset(dataset_name)
        documents = sorted(
            client.list_documents(dataset["id"]),
            key=lambda item: str(item.get("name") or ""),
        )
        if args.document_prefix:
            documents = [
                item
                for item in documents
                if str(item.get("name") or "").startswith(args.document_prefix)
            ]
        dataset_chunk_start = len(chunk_records)
        included_documents = 0
        for index, document in enumerate(documents, start=1):
            name = str(document.get("name") or "")
            document_chunk_start = len(chunk_records)
            chunks = sorted(
                client.list_all_chunks(dataset["id"], document["id"]),
                key=lambda item: str(item.get("id") or item.get("chunk_id") or ""),
            )
            for chunk in chunks:
                if args.max_total_chunks and len(chunk_records) >= args.max_total_chunks:
                    stop = True
                    break
                item = dict(chunk)
                item["document_name"] = name
                item["document_code"] = document_code(name)
                item["source_dataset_id"] = str(dataset["id"])
                item["source_dataset_name"] = dataset_name
                raw_title = chunk.get("title") or chunk.get("important_keywords")
                if isinstance(raw_title, list):
                    raw_title = "｜".join(str(value) for value in raw_title)
                item["title"] = str(raw_title or name)
                chunk_records.append(item)
            if len(chunk_records) > document_chunk_start:
                included_documents += 1
            print(
                f"[{dataset_name} {index}/{len(documents)}] "
                f"{name}｜切片：{len(chunks)}"
            )
            if stop:
                break
        source_datasets.append(
            {
                "id": str(dataset["id"]),
                "name": dataset_name,
                "available_document_count": len(documents),
                "document_count": included_documents,
                "included_chunk_count": len(chunk_records) - dataset_chunk_start,
            }
        )
        if stop:
            break

    with args.schema.open("r", encoding="utf-8-sig") as handle:
        schema = json.load(handle)
    graph = build_graph_dataset_from_chunks(
        chunk_records,
        schema,
        name="-".join(dataset_names) + "-ragflow-chunk-graph-v2",
        max_evidence_per_pair=args.max_evidence_per_pair,
    )
    graph["generated_at"] = datetime.now(timezone.utc).isoformat()
    graph["source_datasets"] = source_datasets
    graph["source_dataset"] = {
        "name": " + ".join(item["name"] for item in source_datasets),
        "document_count": sum(item["document_count"] for item in source_datasets),
        "chunk_count": len(chunk_records),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("=" * 60)
    print(f"知识库数：{len(source_datasets)}")
    print(f"文档数：{graph['source_dataset']['document_count']}")
    print(f"切片数：{len(chunk_records)}")
    print(f"实体数：{len(graph['nodes'])}")
    print(f"可追溯关系数：{len(graph['relations'])}")
    print(f"图索引：{args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

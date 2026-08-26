import argparse
import concurrent.futures
import glob
import hashlib
import json
import os
import re
import sqlite3
import statistics
import sys
import time
from collections import Counter as CollectionCounter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)
from prometheus_client.exposition import write_to_textfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
PIPELINE_VERSION = "1.2.1"
SUPPORTED_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".pdf",
    ".docx",
}
PARSER_BY_SUFFIX = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".pdf": "docling",
    ".docx": "docling",
}
INDEX_MODES = {"ragflow_native", "manual_chunks"}
CHINESE_SEPARATORS = [
    "\n\n",
    "\n",
    "。",
    "；",
    "！？",
    "！",
    "？",
    ". ",
    "; ",
    ", ",
    "，",
    " ",
    "",
]
FDA_CLEARANCE_BOILERPLATE_MARKERS = (
    "We have reviewed your section 510(k) premarket notification",
    "Please be advised that FDA's issuance of a substantial equivalence",
    "The 510(k) Premarket Notification Database available at",
    "Misbranding by reference to premarket notification",
    "All medical devices, including Class I and unclassified devices",
    "For additional information on these requirements, please see the UDI",
    "Your device is also subject to, among other requirements, the Quality System",
    "You must comply with all the Act's requirements",
    "CONTINUE ON A SEPARATE PAGE IF NEEDED",
    "For comprehensive regulatory information about medical devices",
    "DEPARTMENT OF HEALTH AND HUMAN SERVICES",
)


def configure_local_model_cache() -> Path:
    """Keep Docling/Hugging Face artifacts inside the writable workspace."""
    cache_root = PROJECT_ROOT / "data" / "processed" / ".cache"
    huggingface_cache = cache_root / "huggingface"
    huggingface_hub_cache = huggingface_cache / "hub"
    torch_cache = cache_root / "torch"
    for path in (huggingface_cache, huggingface_hub_cache, torch_cache):
        path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(huggingface_cache))
    os.environ.setdefault("HF_HUB_CACHE", str(huggingface_hub_cache))
    os.environ.setdefault("TORCH_HOME", str(torch_cache))
    return cache_root


@dataclass(frozen=True)
class DocumentSpec:
    document_code: str
    path: str
    title: str
    parser: str
    chunk_size: int
    chunk_overlap: int
    chunk_method: str
    index_mode: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ParseResult:
    document_code: str
    source_path: str
    source_sha256: str
    pipeline_signature: str
    parser: str
    output_dir: str
    structured_path: str
    chunks_path: str
    report_path: str
    chunk_count: int
    duration_seconds: float
    quality: dict[str, Any]


class IngestionStateStore:
    """SQLite checkpoint store; only the parent process writes to it."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ingestion_documents (
                source_path TEXT PRIMARY KEY,
                document_code TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                pipeline_signature TEXT NOT NULL,
                parser TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                output_dir TEXT,
                ragflow_document_id TEXT,
                ragflow_document_name TEXT,
                error TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def close(self):
        self.connection.close()

    def get(self, source_path: str):
        row = self.connection.execute(
            "SELECT * FROM ingestion_documents WHERE source_path = ?",
            (source_path,),
        ).fetchone()
        return dict(row) if row else None

    def mark(
        self,
        spec: DocumentSpec,
        source_sha256: str,
        pipeline_signature: str,
        status: str,
        *,
        chunk_count: int = 0,
        output_dir: str = "",
        ragflow_document_id: str = "",
        ragflow_document_name: str = "",
        error: str = "",
        increment_attempt: bool = False,
    ):
        current = self.get(spec.path)
        attempts = int((current or {}).get("attempts", 0))
        if increment_attempt:
            attempts += 1
        if current:
            ragflow_document_id = (
                ragflow_document_id
                or current.get("ragflow_document_id", "")
            )
            ragflow_document_name = (
                ragflow_document_name
                or current.get("ragflow_document_name", "")
            )
        self.connection.execute(
            """
            INSERT INTO ingestion_documents (
                source_path, document_code, source_sha256,
                pipeline_signature, parser, status, attempts,
                chunk_count, output_dir, ragflow_document_id,
                ragflow_document_name, error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_path) DO UPDATE SET
                document_code = excluded.document_code,
                source_sha256 = excluded.source_sha256,
                pipeline_signature = excluded.pipeline_signature,
                parser = excluded.parser,
                status = excluded.status,
                attempts = excluded.attempts,
                chunk_count = excluded.chunk_count,
                output_dir = excluded.output_dir,
                ragflow_document_id = excluded.ragflow_document_id,
                ragflow_document_name = excluded.ragflow_document_name,
                error = excluded.error,
                updated_at = excluded.updated_at
            """,
            (
                spec.path,
                spec.document_code,
                source_sha256,
                pipeline_signature,
                spec.parser,
                status,
                attempts,
                chunk_count,
                output_dir,
                ragflow_document_id,
                ragflow_document_name,
                error,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.connection.commit()


class IngestionMetrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.documents = Counter(
            "mdtr_ingestion_documents_total",
            "Documents handled by the batch ingestion pipeline.",
            ("status", "parser"),
            registry=self.registry,
        )
        self.duration = Histogram(
            "mdtr_ingestion_stage_duration_seconds",
            "Ingestion stage duration in seconds.",
            ("stage", "parser"),
            registry=self.registry,
        )
        self.chunks = Counter(
            "mdtr_ingestion_chunks_total",
            "Chunks generated or indexed by parser.",
            ("stage", "parser"),
            registry=self.registry,
        )
        self.success_rate = Gauge(
            "mdtr_ingestion_last_run_success_ratio",
            "Success ratio of the latest batch ingestion run.",
            registry=self.registry,
        )

    def write(self, destination: Path, success: int, total: int):
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.success_rate.set(success / total if total else 0.0)
        write_to_textfile(str(destination), self.registry)


def read_text_with_fallback(path: Path):
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"无法使用UTF-8或GB18030读取：{path}")


def normalize_markdown(text: str):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip() + "\n"


def sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_component(value: str):
    value = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", value)
    return value.strip("._")[:120] or "document"


def infer_document_code(path: Path):
    match = re.match(
        r"(?i)^((?:DOC|STD|PRACTICE)[-_]?\d{1,4})",
        path.stem,
    )
    if match:
        return match.group(1).replace("-", "").replace("_", "").upper()
    return safe_component(path.stem).upper()


def resolve_path(value: str, manifest_path: Path):
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    project_candidate = (PROJECT_ROOT / candidate).resolve()
    manifest_candidate = (manifest_path.parent / candidate).resolve()
    if project_candidate.exists() or not manifest_candidate.exists():
        return project_candidate
    return manifest_candidate


def load_manifest(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("摄取清单schema_version必须为1")
    defaults = payload.get("defaults", {})
    raw_documents = list(payload.get("documents", []))

    for source in payload.get("sources", []):
        if not source.get("enabled", True):
            continue
        pattern = source.get("glob", "").strip()
        if not pattern:
            raise ValueError("sources中的glob不能为空")
        absolute_pattern = str(resolve_path(pattern, path))
        for matched in glob.glob(absolute_pattern, recursive=True):
            file_path = Path(matched)
            if file_path.is_file() and file_path.suffix.casefold() in SUPPORTED_EXTENSIONS:
                raw_documents.append({**source, "path": str(file_path)})

    specs = []
    seen_paths = set()
    for raw in raw_documents:
        if not raw.get("enabled", True):
            continue
        merged = {**defaults, **raw}
        if not merged.get("path"):
            raise ValueError("documents中的path不能为空")
        source_path = resolve_path(str(merged["path"]), path)
        if not source_path.is_file():
            raise FileNotFoundError(f"清单文件不存在：{source_path}")
        if source_path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型：{source_path.suffix}")
        normalized_path = str(source_path)
        if normalized_path.casefold() in seen_paths:
            continue
        seen_paths.add(normalized_path.casefold())

        parser_name = str(merged.get("parser", "auto")).casefold()
        if parser_name == "auto":
            parser_name = PARSER_BY_SUFFIX[source_path.suffix.casefold()]
        if parser_name not in {
            "markdown",
            "text",
            "docling",
            "docling_text_pdf",
        }:
            raise ValueError(f"不支持的解析器：{parser_name}")
        index_mode = str(
            merged.get("index_mode", "ragflow_native")
        ).casefold()
        if index_mode not in INDEX_MODES:
            raise ValueError(f"不支持的index_mode：{index_mode}")
        chunk_size = int(merged.get("chunk_size", 800))
        chunk_overlap = int(merged.get("chunk_overlap", 80))
        if chunk_size < 100:
            raise ValueError("chunk_size不能小于100")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap必须大于等于0且小于chunk_size")

        specs.append(
            DocumentSpec(
                document_code=str(
                    merged.get("document_code")
                    or infer_document_code(source_path)
                ).strip(),
                path=normalized_path,
                title=str(merged.get("title") or source_path.stem).strip(),
                parser=parser_name,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                chunk_method=str(merged.get("chunk_method", "naive")),
                index_mode=index_mode,
                metadata=dict(merged.get("metadata", {})),
            )
        )
    return payload, specs


def pipeline_signature(spec: DocumentSpec):
    configuration = {
        "pipeline_version": PIPELINE_VERSION,
        "parser": spec.parser,
        "chunk_size": spec.chunk_size,
        "chunk_overlap": spec.chunk_overlap,
        "separators": CHINESE_SEPARATORS,
    }
    serialized = json.dumps(
        configuration, ensure_ascii=False, sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def parse_with_docling(path: Path, disable_ocr: bool = False):
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise RuntimeError(
            "解析PDF/DOCX需要Docling。请运行："
            "python -m pip install -r requirements-ingestion.txt"
        ) from exc
    if disable_ocr and path.suffix.casefold() == ".pdf":
        from docling.backend.pypdfium2_backend import (
            PyPdfiumDocumentBackend,
        )
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False
        pipeline_options.do_table_structure = True
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                    backend=PyPdfiumDocumentBackend,
                )
            }
        )
    else:
        converter = DocumentConverter()
    result = converter.convert(path)
    return result.document.export_to_markdown()


def split_markdown(spec: DocumentSpec, markdown: str):
    try:
        from langchain_text_splitters import (
            MarkdownHeaderTextSplitter,
            RecursiveCharacterTextSplitter,
        )
    except ImportError as exc:
        raise RuntimeError(
            "切片需要langchain-text-splitters。请运行："
            "python -m pip install -r requirements-ingestion.txt"
        ) from exc

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "h1"),
            ("##", "h2"),
            ("###", "h3"),
            ("####", "h4"),
            ("#####", "h5"),
            ("######", "h6"),
        ],
        strip_headers=False,
    )
    header_documents = header_splitter.split_text(markdown)
    if not header_documents:
        from langchain_core.documents import Document

        header_documents = [Document(page_content=markdown, metadata={})]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=spec.chunk_size,
        chunk_overlap=spec.chunk_overlap,
        separators=CHINESE_SEPARATORS,
        keep_separator=True,
        length_function=len,
    )
    split_documents = splitter.split_documents(header_documents)
    chunks = []
    filtered = CollectionCounter()
    seen_hashes: set[str] = set()
    for document in split_documents:
        content = document.page_content.strip()
        if not content:
            continue
        headers = {
            key: value
            for key, value in document.metadata.items()
            if key.startswith("h") and value
        }
        breadcrumb = " > ".join(headers.values())
        if "DO NOT SEND YOUR COMPLETED FORM TO THE PRA STAFF" in content:
            filtered["boilerplate"] += 1
            continue
        if any(
            marker.casefold() in content.casefold()
            for marker in FDA_CLEARANCE_BOILERPLATE_MARKERS
        ):
            filtered["boilerplate"] += 1
            continue
        if any(
            token in content
            for token in ("\ufffd", "锟斤拷", "鏂囧瓧", "缂哄皯")
        ):
            filtered["mojibake"] += 1
            continue
        semantic_lines = []
        for line in content.splitlines():
            candidate = re.sub(r"<!--.*?-->", " ", line)
            candidate = re.sub(r"^\s*#{1,6}\s*", "", candidate)
            candidate = re.sub(r"[#*_`>|\\\-]+", " ", candidate)
            candidate = re.sub(
                rf"\b{re.escape(spec.document_code)}\b",
                " ",
                candidate,
                flags=re.IGNORECASE,
            )
            candidate = " ".join(candidate.split())
            if candidate:
                semantic_lines.append(candidate)
        semantic_text = " ".join(semantic_lines)
        non_heading_lines = [
            line
            for line in content.splitlines()
            if line.strip()
            and not line.lstrip().startswith("#")
            and "<!-- image -->" not in line
        ]
        if not non_heading_lines:
            filtered["heading_or_image_only"] += 1
            continue
        if len(semantic_text) < 20:
            filtered["low_information"] += 1
            continue
        prefix_parts = [
            f"来源文档：{spec.document_code}｜{spec.title}",
        ]
        if breadcrumb:
            prefix_parts.append(f"章节路径：{breadcrumb}")
        retrieval_text = "\n".join(prefix_parts) + "\n\n" + content
        chunk_hash = hashlib.sha256(
            retrieval_text.encode("utf-8")
        ).hexdigest()
        if chunk_hash in seen_hashes:
            continue
        seen_hashes.add(chunk_hash)
        index = len(chunks) + 1
        chunks.append(
            {
                "chunk_index": index,
                "chunk_id": f"{spec.document_code}-{index:05d}-{chunk_hash[:12]}",
                "document_code": spec.document_code,
                "document_title": spec.title,
                "source_path": spec.path,
                "headers": headers,
                "breadcrumb": breadcrumb,
                "content": content,
                "retrieval_text": retrieval_text,
                "content_sha256": chunk_hash,
                "metadata": spec.metadata,
            }
        )
    return chunks, dict(filtered)


def percentile(values, percentage):
    if not values:
        return 0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentage
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(
        ordered[lower] * (1 - fraction) + ordered[upper] * fraction,
        2,
    )


def audit_local_chunks(chunks, chunk_size, filtered=None):
    lengths = [len(chunk["content"]) for chunk in chunks]
    hashes = [chunk["content_sha256"] for chunk in chunks]
    suspicious_tokens = ("\ufffd", "锟斤拷", "鏂囧瓧", "缂哄皯")
    result = {
        "chunk_count": len(chunks),
        "empty_chunk_count": sum(not chunk["content"].strip() for chunk in chunks),
        "very_short_chunk_count": sum(0 < length < 40 for length in lengths),
        "very_long_chunk_count": sum(
            length > chunk_size * 1.5 for length in lengths
        ),
        "duplicate_chunk_count": len(hashes) - len(set(hashes)),
        "missing_heading_count": sum(
            not chunk["breadcrumb"] for chunk in chunks
        ),
        "mojibake_chunk_count": sum(
            any(token in chunk["content"] for token in suspicious_tokens)
            for chunk in chunks
        ),
        "length_min": min(lengths) if lengths else 0,
        "length_median": statistics.median(lengths) if lengths else 0,
        "length_p95": percentile(lengths, 0.95),
        "length_max": max(lengths) if lengths else 0,
    }
    for reason, count in (filtered or {}).items():
        result[f"filtered_{reason}_chunk_count"] = count
    result["filtered_chunk_count"] = sum((filtered or {}).values())
    return result


def atomic_write_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def parse_document_worker(payload):
    spec = DocumentSpec(**payload["spec"])
    source_sha256 = payload["source_sha256"]
    signature = payload["pipeline_signature"]
    output_root = Path(payload["output_root"])
    started = time.monotonic()
    source_path = Path(spec.path)
    document_dir = output_root / (
        f"{safe_component(spec.document_code)}__{source_sha256[:12]}"
    )
    source_stem = safe_component(source_path.stem)
    structured_path = document_dir / f"{source_stem}_structured.md"
    reuse_structured = bool(
        payload.get("reuse_structured") and structured_path.is_file()
    )

    if reuse_structured:
        markdown = structured_path.read_text(encoding="utf-8")
    elif spec.parser in {"markdown", "text"}:
        markdown = read_text_with_fallback(source_path)
        if spec.parser == "text":
            markdown = f"# {spec.document_code}｜{spec.title}\n\n{markdown}"
    elif spec.parser in {"docling", "docling_text_pdf"}:
        markdown = parse_with_docling(
            source_path,
            disable_ocr=spec.parser == "docling_text_pdf",
        )
    else:
        raise ValueError(f"未知解析器：{spec.parser}")

    markdown = normalize_markdown(markdown)
    if not re.match(r"^\s*#\s+", markdown):
        markdown = f"# {spec.document_code}｜{spec.title}\n\n{markdown}"
    chunks, filtered = split_markdown(spec, markdown)
    if not chunks:
        raise RuntimeError("解析后没有生成任何有效切片")
    quality = audit_local_chunks(chunks, spec.chunk_size, filtered)

    chunks_path = document_dir / "chunks.jsonl"
    report_path = document_dir / "quality_report.json"
    atomic_write_text(structured_path, markdown)
    atomic_write_text(
        chunks_path,
        "\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in chunks)
        + "\n",
    )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_version": PIPELINE_VERSION,
        "document": asdict(spec),
        "source_sha256": source_sha256,
        "pipeline_signature": signature,
        "structured_reused": reuse_structured,
        "quality": quality,
        "artifacts": {
            "structured_path": str(structured_path),
            "chunks_path": str(chunks_path),
            "report_path": str(report_path),
        },
    }
    atomic_write_text(
        report_path,
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    return asdict(
        ParseResult(
            document_code=spec.document_code,
            source_path=spec.path,
            source_sha256=source_sha256,
            pipeline_signature=signature,
            parser=spec.parser,
            output_dir=str(document_dir),
            structured_path=str(structured_path),
            chunks_path=str(chunks_path),
            report_path=str(report_path),
            chunk_count=len(chunks),
            duration_seconds=round(time.monotonic() - started, 4),
            quality=quality,
        )
    )


def load_cached_result(state):
    report_path = Path(state.get("output_dir", "")) / "quality_report.json"
    if not report_path.is_file():
        return None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    artifacts = report["artifacts"]
    return ParseResult(
        document_code=report["document"]["document_code"],
        source_path=report["document"]["path"],
        source_sha256=report["source_sha256"],
        pipeline_signature=report["pipeline_signature"],
        parser=report["document"]["parser"],
        output_dir=str(report_path.parent),
        structured_path=artifacts["structured_path"],
        chunks_path=artifacts["chunks_path"],
        report_path=artifacts["report_path"],
        chunk_count=int(report["quality"]["chunk_count"]),
        duration_seconds=0.0,
        quality=report["quality"],
    )


def load_chunk_records(result: ParseResult):
    records = []
    with Path(result.chunks_path).open(encoding="utf-8") as source:
        for line in source:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def ingest_result_to_ragflow(
    spec: DocumentSpec,
    result: ParseResult,
    dataset_name: str,
    reuse_existing: bool,
    wait_seconds: int,
    poll_seconds: int,
):
    from scripts.ingest_single_document import (
        RAGFlowIngestionClient,
        chunk_text,
        normalized_state,
    )

    started = time.monotonic()
    client = RAGFlowIngestionClient()
    dataset = client.find_dataset(dataset_name)
    structured_path = Path(result.structured_path)
    upload_name = structured_path.name
    existing = [
        document
        for document in client.list_documents(dataset["id"])
        if document.get("name", "").casefold() == upload_name.casefold()
    ]
    if existing and not reuse_existing:
        raise RuntimeError(
            f"RAGFlow已存在同名文档{upload_name}；"
            "为防止覆盖或复用旧版本，本次未写入。"
            "确认属于同一版本后可增加--reuse-existing。"
        )
    if existing:
        document = existing[0]
    else:
        try:
            document = client.upload_document(
                dataset["id"], structured_path, upload_name=upload_name
            )
        except (requests.ConnectionError, requests.Timeout) as upload_error:
            # RAGFlow may accept the multipart upload before the HTTP connection
            # closes. Reconcile by the deterministic upload name before retrying,
            # otherwise a resume run could create duplicate remote documents.
            document = None
            for attempt in range(3):
                if attempt:
                    time.sleep(2)
                matches = [
                    candidate
                    for candidate in client.list_documents(dataset["id"])
                    if candidate.get("name", "").casefold()
                    == upload_name.casefold()
                ]
                if len(matches) > 1:
                    raise RuntimeError(
                        f"RAGFlow存在多个同名文档：{upload_name}"
                    ) from upload_error
                if matches:
                    document = matches[0]
                    break
            if document is None:
                raise upload_error

    if spec.index_mode == "manual_chunks":
        local_chunks = load_chunk_records(result)
        remote_chunks = client.list_all_chunks(dataset["id"], document["id"])
        remote_hashes = {
            hashlib.sha256(
                chunk_text(chunk).strip().encode("utf-8")
            ).hexdigest()
            for chunk in remote_chunks
            if chunk_text(chunk).strip()
        }
        created = 0
        for chunk in local_chunks:
            content = chunk["retrieval_text"].strip()
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if content_hash in remote_hashes:
                continue
            client.create_chunk(dataset["id"], document["id"], content)
            remote_hashes.add(content_hash)
            created += 1
        final_chunks = client.list_all_chunks(dataset["id"], document["id"])
        return {
            "document_id": document["id"],
            "document_name": document.get("name", upload_name),
            "chunk_count": len(final_chunks),
            "created_chunk_count": created,
            "duration_seconds": round(time.monotonic() - started, 4),
        }

    current_method = (
        document.get("chunk_method") or document.get("parser_id") or ""
    ).lower()
    if spec.chunk_method and current_method != spec.chunk_method:
        document = client.update_chunk_method(
            dataset["id"], document["id"], spec.chunk_method
        )
    state = normalized_state(document.get("run", ""))
    if state in {"UNSTART", "FAIL"}:
        client.start_parsing(dataset["id"], document["id"])
    elif state == "CANCEL":
        raise RuntimeError(f"RAGFlow文档已取消：{upload_name}")
    if state != "DONE":
        document = client.wait_for_document(
            dataset["id"],
            document["id"],
            wait_seconds=wait_seconds,
            poll_seconds=poll_seconds,
        )
    chunks = client.list_all_chunks(dataset["id"], document["id"])
    if not chunks:
        raise RuntimeError(f"RAGFlow解析完成但未生成切片：{upload_name}")
    return {
        "document_id": document["id"],
        "document_name": document.get("name", upload_name),
        "chunk_count": len(chunks),
        "created_chunk_count": 0,
        "duration_seconds": round(time.monotonic() - started, 4),
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "基于LangChain、Docling、SQLite和RAGFlow API的"
            "可恢复批量文档摄取管线。"
        )
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="将验证通过的文档写入RAGFlow；缺省仅生成本地产物。",
    )
    parser.add_argument(
        "--dataset-name",
        help="目标RAGFlow知识库；--apply时可省略并从.env推断。",
    )
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--ragflow-workers", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--reuse-structured",
        action="store_true",
        help=(
            "若本地产物中已有结构化Markdown，则跳过Docling并仅重新切片；"
            "适用于清洗规则或切片参数变更后的快速重跑。"
        ),
    )
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="复用RAGFlow中的同名结构化文档，用于中断后续跑。",
    )
    parser.add_argument("--wait-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--metrics-output", type=Path)
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=0,
        help="运行期间暴露Prometheus指标的端口；0表示不启动HTTP端点。",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    model_cache = configure_local_model_cache()
    manifest_path = args.manifest.expanduser().resolve()
    manifest, specs = load_manifest(manifest_path)
    if not specs:
        raise RuntimeError("清单中没有启用的文档")
    defaults = manifest.get("defaults", {})
    output_root = (
        args.output_dir
        or Path(defaults.get("output_dir", "data/processed/ingestion"))
    )
    state_db = (
        args.state_db
        or Path(defaults.get("state_db", "data/processed/ingestion_state.sqlite3"))
    )
    metrics_output = (
        args.metrics_output
        or Path(defaults.get("metrics_output", "data/processed/ingestion/metrics.prom"))
    )
    output_root = (PROJECT_ROOT / output_root).resolve() if not output_root.is_absolute() else output_root.resolve()
    state_db = (PROJECT_ROOT / state_db).resolve() if not state_db.is_absolute() else state_db.resolve()
    metrics_output = (PROJECT_ROOT / metrics_output).resolve() if not metrics_output.is_absolute() else metrics_output.resolve()
    workers = max(1, min(args.workers, 8))
    ragflow_workers = max(1, min(args.ragflow_workers, 4))
    metrics = IngestionMetrics()
    if args.metrics_port:
        start_http_server(args.metrics_port, registry=metrics.registry)
        print(
            "Prometheus实时指标："
            f"http://127.0.0.1:{args.metrics_port}/metrics"
        )
    state_store = IngestionStateStore(state_db)
    started_at = time.monotonic()
    results: dict[str, ParseResult] = {}
    failures: dict[str, str] = {}
    pending = []
    spec_by_path = {spec.path: spec for spec in specs}

    print(f"清单：{manifest_path}")
    print(f"文档数：{len(specs)}｜解析进程：{workers}")
    print(f"状态库：{state_db}")
    print(f"输出目录：{output_root}")
    print(f"模型缓存：{model_cache}")
    print(f"模式：{'APPLY' if args.apply else 'DRY-RUN'}")

    try:
        for spec in specs:
            source_sha256 = sha256_file(Path(spec.path))
            signature = pipeline_signature(spec)
            state = state_store.get(spec.path)
            cache_valid = bool(
                state
                and state.get("source_sha256") == source_sha256
                and state.get("pipeline_signature") == signature
                and state.get("status") in {"validated", "indexed"}
                and not args.force
            )
            cached = load_cached_result(state) if cache_valid else None
            if cached:
                results[spec.path] = cached
                metrics.documents.labels("cached", spec.parser).inc()
                print(
                    f"[CACHE] {spec.document_code}｜"
                    f"切片{cached.chunk_count}｜{Path(spec.path).name}"
                )
                continue
            state_store.mark(
                spec,
                source_sha256,
                signature,
                "parsing",
                increment_attempt=True,
            )
            pending.append(
                {
                    "spec": asdict(spec),
                    "source_sha256": source_sha256,
                    "pipeline_signature": signature,
                    "output_root": str(output_root),
                    "reuse_structured": args.reuse_structured,
                }
            )

        if pending:
            with concurrent.futures.ProcessPoolExecutor(
                max_workers=workers
            ) as executor:
                future_map = {
                    executor.submit(parse_document_worker, payload): payload
                    for payload in pending
                }
                for future in concurrent.futures.as_completed(future_map):
                    payload = future_map[future]
                    spec = DocumentSpec(**payload["spec"])
                    try:
                        result = ParseResult(**future.result())
                        results[spec.path] = result
                        state_store.mark(
                            spec,
                            result.source_sha256,
                            result.pipeline_signature,
                            "validated",
                            chunk_count=result.chunk_count,
                            output_dir=result.output_dir,
                        )
                        metrics.documents.labels("success", spec.parser).inc()
                        metrics.duration.labels("parse", spec.parser).observe(
                            result.duration_seconds
                        )
                        metrics.chunks.labels("generated", spec.parser).inc(
                            result.chunk_count
                        )
                        print(
                            f"[OK] {spec.document_code}｜"
                            f"切片{result.chunk_count}｜"
                            f"{result.duration_seconds:.2f}s"
                        )
                    except Exception as exc:
                        message = repr(exc)
                        failures[spec.path] = message
                        state_store.mark(
                            spec,
                            payload["source_sha256"],
                            payload["pipeline_signature"],
                            "failed",
                            error=message,
                        )
                        metrics.documents.labels("failed", spec.parser).inc()
                        print(
                            f"[FAIL] {spec.document_code}｜{message}",
                            file=sys.stderr,
                        )

        if args.apply and results:
            from scripts.ingest_single_document import RAGFlowIngestionClient

            dataset_name = (args.dataset_name or "").strip()
            if not dataset_name:
                dataset_name = RAGFlowIngestionClient().infer_dataset_name()
            if not dataset_name:
                raise RuntimeError(
                    "无法确定目标知识库，请使用--dataset-name或配置"
                    "RAGFLOW_DATASET_NAME。"
                )
            print(
                f"开始写入RAGFlow：{dataset_name}｜并发{ragflow_workers}"
            )
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=ragflow_workers
            ) as executor:
                future_map = {
                    executor.submit(
                        ingest_result_to_ragflow,
                        spec_by_path[path],
                        result,
                        dataset_name,
                        args.reuse_existing,
                        args.wait_seconds,
                        args.poll_seconds,
                    ): path
                    for path, result in results.items()
                    if (
                        args.force
                        or (state_store.get(path) or {}).get("status")
                        != "indexed"
                    )
                }
                for future in concurrent.futures.as_completed(future_map):
                    path = future_map[future]
                    spec = spec_by_path[path]
                    result = results[path]
                    try:
                        remote = future.result()
                        state_store.mark(
                            spec,
                            result.source_sha256,
                            result.pipeline_signature,
                            "indexed",
                            chunk_count=remote["chunk_count"],
                            output_dir=result.output_dir,
                            ragflow_document_id=remote["document_id"],
                            ragflow_document_name=remote["document_name"],
                        )
                        metrics.duration.labels(
                            "ragflow_index", spec.parser
                        ).observe(remote["duration_seconds"])
                        metrics.chunks.labels(
                            "indexed", spec.parser
                        ).inc(remote["chunk_count"])
                        print(
                            f"[INDEXED] {spec.document_code}｜"
                            f"RAGFlow切片{remote['chunk_count']}"
                        )
                    except Exception as exc:
                        message = repr(exc)
                        failures[path] = message
                        state_store.mark(
                            spec,
                            result.source_sha256,
                            result.pipeline_signature,
                            "failed",
                            chunk_count=result.chunk_count,
                            output_dir=result.output_dir,
                            error=message,
                        )
                        metrics.documents.labels(
                            "index_failed", spec.parser
                        ).inc()
                        print(
                            f"[INDEX-FAIL] {spec.document_code}｜{message}",
                            file=sys.stderr,
                        )
    finally:
        success_count = len(specs) - len(failures)
        metrics.write(metrics_output, success_count, len(specs))
        state_store.close()

    elapsed = time.monotonic() - started_at
    print("=" * 60)
    print(f"总文档：{len(specs)}")
    print(f"成功：{len(specs) - len(failures)}")
    print(f"失败：{len(failures)}")
    print(f"本地切片：{sum(result.chunk_count for result in results.values())}")
    print(f"总耗时：{elapsed:.2f}s")
    print(f"Prometheus指标：{metrics_output}")
    if failures:
        print("失败文档：")
        for path, error in failures.items():
            print(f"- {Path(path).name}｜{error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

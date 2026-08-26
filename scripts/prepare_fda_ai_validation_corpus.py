"""Prepare a reproducible FDA AI-enabled device validation corpus.

The script downloads the FDA's official AI-enabled device catalog, selects a
diverse set of 510(k) submissions, downloads their public decision summaries,
validates the PDF payloads, and emits an ingestion manifest for
``ingest_batch_documents.py``.

Source PDFs and run reports live under ignored ``data/incoming`` and
``data/processed`` directories.  The compact catalog snapshot and manifest are
safe to commit because they contain metadata and hashes, not the source PDFs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FDA_CATALOG_PAGE = (
    "https://www.fda.gov/medical-devices/software-medical-device-samd/"
    "artificial-intelligence-enabled-medical-devices"
)
FDA_CATALOG_CSV = "https://www.fda.gov/media/178541/download?attachment"
SUBMISSION_PATTERN = re.compile(r"^K\d{6}$", re.IGNORECASE)
MINIMUM_PDF_BYTES = 10_000


@dataclass(frozen=True)
class DeviceRecord:
    decision_date: str
    submission_number: str
    device: str
    company: str
    panel: str
    product_code: str

    @property
    def parsed_date(self) -> datetime:
        return datetime.strptime(self.decision_date, "%m/%d/%Y")

    @property
    def pdf_url(self) -> str:
        year = self.submission_number[1:3]
        return (
            "https://www.accessdata.fda.gov/cdrh_docs/"
            f"pdf{year}/{self.submission_number.upper()}.pdf"
        )


def project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_valid_pdf(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < MINIMUM_PDF_BYTES:
        return False
    with path.open("rb") as source:
        return source.read(5) == b"%PDF-"


def fetch_catalog(destination: Path, timeout_seconds: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(
        FDA_CATALOG_CSV,
        headers={"User-Agent": "medical-device-test-rag/1.0"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    if "Submission Number" not in response.text[:500]:
        raise RuntimeError("FDA AI医疗器械CSV响应格式异常")
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(response.content)
    temporary.replace(destination)


def read_catalog(path: Path) -> list[DeviceRecord]:
    records: list[DeviceRecord] = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            submission = (row.get("Submission Number") or "").strip().upper()
            decision_date = (row.get("Date of Final Decision") or "").strip()
            if not SUBMISSION_PATTERN.fullmatch(submission):
                continue
            try:
                datetime.strptime(decision_date, "%m/%d/%Y")
            except ValueError:
                continue
            records.append(
                DeviceRecord(
                    decision_date=decision_date,
                    submission_number=submission,
                    device=(row.get("Device") or "").strip(),
                    company=(row.get("Company") or "").strip(),
                    panel=(row.get("Panel (Lead)") or "Unknown").strip()
                    or "Unknown",
                    product_code=(row.get("Primary Product Code") or "").strip(),
                )
            )
    records.sort(key=lambda record: record.parsed_date, reverse=True)
    return records


def prioritize_records(
    records: Iterable[DeviceRecord], radiology_cap: int
) -> list[DeviceRecord]:
    """Keep recent records while stopping Radiology from dominating the corpus."""
    preferred: list[DeviceRecord] = []
    overflow: list[DeviceRecord] = []
    radiology_count = 0
    for record in records:
        if record.panel.casefold() == "radiology":
            if radiology_count >= radiology_cap:
                overflow.append(record)
                continue
            radiology_count += 1
        preferred.append(record)
    return preferred + overflow


def download_pdf(
    record: DeviceRecord,
    output_dir: Path,
    timeout_seconds: int,
    retries: int,
) -> dict:
    output_path = output_dir / f"FDAAI_{record.submission_number}.pdf"
    if is_valid_pdf(output_path):
        return {
            "record": record,
            "path": output_path,
            "status": "cached",
            "sha256": sha256_file(output_path),
            "bytes": output_path.stat().st_size,
            "error": "",
        }

    error = ""
    for attempt in range(1, retries + 2):
        temporary = output_path.with_suffix(".pdf.part")
        try:
            response = requests.get(
                record.pdf_url,
                headers={"User-Agent": "medical-device-test-rag/1.0"},
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            if len(response.content) < MINIMUM_PDF_BYTES:
                raise RuntimeError("PDF响应过短")
            if not response.content.startswith(b"%PDF-"):
                raise RuntimeError("响应不是PDF")
            temporary.write_bytes(response.content)
            temporary.replace(output_path)
            return {
                "record": record,
                "path": output_path,
                "status": "downloaded",
                "sha256": sha256_file(output_path),
                "bytes": output_path.stat().st_size,
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001 - preserve network failure detail
            error = repr(exc)
            temporary.unlink(missing_ok=True)
            if attempt <= retries:
                time.sleep(min(2**attempt, 8))
    return {
        "record": record,
        "path": output_path,
        "status": "failed",
        "sha256": "",
        "bytes": 0,
        "error": error,
    }


def download_until_limit(
    candidates: list[DeviceRecord],
    output_dir: Path,
    limit: int,
    workers: int,
    timeout_seconds: int,
    retries: int,
) -> tuple[list[dict], list[dict]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    successes: list[dict] = []
    failures: list[dict] = []
    cursor = 0
    while len(successes) < limit and cursor < len(candidates):
        remaining = limit - len(successes)
        batch_size = min(max(workers * 2, workers), remaining, len(candidates) - cursor)
        batch = candidates[cursor : cursor + batch_size]
        cursor += batch_size
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    download_pdf,
                    record,
                    output_dir,
                    timeout_seconds,
                    retries,
                ): record
                for record in batch
            }
            for future in as_completed(futures):
                result = future.result()
                if result["status"] == "failed":
                    failures.append(result)
                    print(
                        f"[失败] {result['record'].submission_number} "
                        f"{result['error']}"
                    )
                else:
                    successes.append(result)
                    print(
                        f"[{len(successes)}/{limit}] "
                        f"{result['record'].submission_number} "
                        f"{result['status']} {result['bytes'] / 1024:.1f} KiB"
                    )
    successes.sort(key=lambda item: item["record"].parsed_date, reverse=True)
    return successes[:limit], failures


def manifest_document(result: dict) -> dict:
    record: DeviceRecord = result["record"]
    relative_path = result["path"].relative_to(PROJECT_ROOT).as_posix()
    return {
        "document_code": f"FDAAI_{record.submission_number}",
        "title": f"FDA {record.submission_number} - {record.device}",
        "path": relative_path,
        "metadata": {
            "authority": "FDA",
            "publication_date": record.parsed_date.date().isoformat(),
            "language": "en-US",
            "document_type": "510k_decision_summary",
            "jurisdiction": "United States",
            "knowledge_layer": "real_world_validation_evidence",
            "normative": False,
            "submission_number": record.submission_number,
            "device": record.device,
            "company": record.company,
            "panel": record.panel,
            "product_code": record.product_code,
            "source_url": record.pdf_url,
            "catalog_url": FDA_CATALOG_PAGE,
            "source_sha256": result["sha256"],
        },
    }


def write_manifest(path: Path, results: list[dict]) -> None:
    payload = {
        "schema_version": 1,
        "defaults": {
            "parser": "docling_text_pdf",
            "chunk_size": 900,
            "chunk_overlap": 100,
            "chunk_method": "naive",
            "index_mode": "ragflow_native",
            "output_dir": "data/processed/fda_ai_validation_corpus_v1",
            "state_db": "data/processed/fda_ai_validation_corpus_v1_state.sqlite3",
            "metrics_output": (
                "data/processed/fda_ai_validation_corpus_v1/metrics.prom"
            ),
        },
        "documents": [manifest_document(result) for result in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_catalog(path: Path, results: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "submission_number",
        "decision_date",
        "device",
        "company",
        "panel",
        "product_code",
        "source_url",
        "source_sha256",
        "bytes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for result in results:
            record: DeviceRecord = result["record"]
            writer.writerow(
                {
                    "submission_number": record.submission_number,
                    "decision_date": record.parsed_date.date().isoformat(),
                    "device": record.device,
                    "company": record.company,
                    "panel": record.panel,
                    "product_code": record.product_code,
                    "source_url": record.pdf_url,
                    "source_sha256": result["sha256"],
                    "bytes": result["bytes"],
                }
            )


def write_report(path: Path, results: list[dict], failures: list[dict]) -> None:
    panel_counts = Counter(result["record"].panel for result in results)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog_page": FDA_CATALOG_PAGE,
        "catalog_csv": FDA_CATALOG_CSV,
        "downloaded_or_cached": len(results),
        "failed_attempts": len(failures),
        "total_bytes": sum(result["bytes"] for result in results),
        "panel_counts": dict(sorted(panel_counts.items())),
        "failures": [
            {
                "submission_number": item["record"].submission_number,
                "url": item["record"].pdf_url,
                "error": item["error"],
            }
            for item in failures
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="下载FDA AI医疗器械510(k)公开摘要并生成批量摄取清单。"
    )
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--radiology-cap", type=int, default=120)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--catalog-csv",
        default="data/incoming/fda_ai_enabled_devices.csv",
    )
    parser.add_argument(
        "--download-dir",
        default="data/incoming/fda_ai_validation_corpus_v1",
    )
    parser.add_argument(
        "--manifest-out",
        default="config/document_ingestion_manifest.fda_ai_validation_v1.json",
    )
    parser.add_argument(
        "--catalog-out",
        default="data/catalog/fda_ai_validation_corpus_v1.csv",
    )
    parser.add_argument(
        "--report-out",
        default="data/processed/fda_ai_validation_corpus_v1_download_report.json",
    )
    parser.add_argument(
        "--refresh-catalog",
        action="store_true",
        help="重新下载FDA官方CSV；缺省优先复用本地副本。",
    )
    parser.add_argument(
        "--selection-only",
        action="store_true",
        help="仅打印候选分布，不下载PDF或写出清单。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.limit < 1:
        raise ValueError("--limit必须大于0")
    if args.radiology_cap < 0:
        raise ValueError("--radiology-cap不能小于0")
    if args.workers < 1:
        raise ValueError("--workers必须大于0")

    catalog_csv = project_path(args.catalog_csv)
    if args.refresh_catalog or not catalog_csv.is_file():
        print(f"下载FDA官方目录：{FDA_CATALOG_CSV}")
        fetch_catalog(catalog_csv, args.timeout)
    records = read_catalog(catalog_csv)
    candidates = prioritize_records(records, args.radiology_cap)
    preview = candidates[: args.limit]
    print(f"FDA目录中的510(k)记录：{len(records)}")
    print(f"目标下载：{args.limit}")
    print(f"候选类别：{dict(Counter(item.panel for item in preview))}")
    if args.selection_only:
        return

    started = time.monotonic()
    results, failures = download_until_limit(
        candidates,
        project_path(args.download_dir),
        args.limit,
        args.workers,
        args.timeout,
        args.retries,
    )
    if len(results) < args.limit:
        raise RuntimeError(
            f"仅获得{len(results)}/{args.limit}份有效PDF；请查看下载报告后重试。"
        )

    manifest_out = project_path(args.manifest_out)
    catalog_out = project_path(args.catalog_out)
    report_out = project_path(args.report_out)
    write_manifest(manifest_out, results)
    write_catalog(catalog_out, results)
    write_report(report_out, results, failures)
    print("=" * 60)
    print(f"有效PDF：{len(results)}")
    print(f"失败尝试：{len(failures)}")
    print(f"总大小：{sum(item['bytes'] for item in results) / 1024 / 1024:.1f} MiB")
    print(f"耗时：{time.monotonic() - started:.1f}秒")
    print(f"摄取清单：{manifest_out}")
    print(f"元数据目录：{catalog_out}")
    print(f"下载报告：{report_out}")


if __name__ == "__main__":
    main()

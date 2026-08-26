"""Aggregate document-ingestion quality reports and JSONL chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


MARKUP_RE = re.compile(r"<!--.*?-->|[#*_`>|\-]+", re.DOTALL)
DOC_CODE_RE = re.compile(r"\b(?:FDAAI_)?K\d{6}\b", re.IGNORECASE)


def percentile(values: list[int], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def normalize_for_information_check(content: str) -> str:
    text = MARKUP_RE.sub(" ", content)
    text = DOC_CODE_RE.sub(" ", text)
    return " ".join(text.split()).strip()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(input_dir: Path) -> dict[str, Any]:
    report_paths = sorted(input_dir.rglob("quality_report.json"))
    if not report_paths:
        raise RuntimeError(f"未找到quality_report.json：{input_dir}")

    quality_totals: Counter[str] = Counter()
    chunk_lengths: list[int] = []
    content_hashes: Counter[str] = Counter()
    content_documents: dict[str, set[str]] = {}
    content_previews: dict[str, str] = {}
    source_hashes: Counter[str] = Counter()
    low_information = 0
    low_information_samples: list[dict[str, Any]] = []
    malformed_jsonl = 0
    documents: list[dict[str, Any]] = []
    count_fields = (
        "chunk_count",
        "empty_chunk_count",
        "very_short_chunk_count",
        "very_long_chunk_count",
        "duplicate_chunk_count",
        "missing_heading_count",
        "mojibake_chunk_count",
        "filtered_chunk_count",
        "filtered_boilerplate_chunk_count",
        "filtered_mojibake_chunk_count",
        "filtered_heading_or_image_only_chunk_count",
        "filtered_low_information_chunk_count",
    )

    for report_path in report_paths:
        report = load_json(report_path)
        quality = report["quality"]
        document = report["document"]
        for field in count_fields:
            quality_totals[field] += int(quality.get(field, 0))
        source_hashes[report["source_sha256"]] += 1

        chunks_path = Path(report["artifacts"]["chunks_path"])
        observed_chunks = 0
        with chunks_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    malformed_jsonl += 1
                    continue
                content = str(chunk.get("content", ""))
                observed_chunks += 1
                chunk_lengths.append(len(content))
                # Ingestion chunk hashes include the source prefix, which is
                # intentionally unique per document. Hash raw content here so
                # boilerplate repeated across different documents is visible.
                digest = hashlib.sha256(
                    content.encode("utf-8")
                ).hexdigest()
                content_hashes[digest] += 1
                content_documents.setdefault(digest, set()).add(
                    document["document_code"]
                )
                content_previews.setdefault(digest, content[:240])
                normalized = normalize_for_information_check(content)
                if len(normalized) < 40:
                    low_information += 1
                    if len(low_information_samples) < 25:
                        low_information_samples.append(
                            {
                                "document_code": document["document_code"],
                                "chunk_index": chunk.get("chunk_index"),
                                "normalized_length": len(normalized),
                                "content_preview": content[:240],
                            }
                        )

        documents.append(
            {
                "document_code": document["document_code"],
                "title": document["title"],
                "chunk_count": int(quality["chunk_count"]),
                "observed_chunk_count": observed_chunks,
                "very_short_chunk_count": int(
                    quality.get("very_short_chunk_count", 0)
                ),
                "mojibake_chunk_count": int(
                    quality.get("mojibake_chunk_count", 0)
                ),
            }
        )

    exact_duplicate_extra = sum(
        len(document_codes) - 1
        for document_codes in content_documents.values()
        if len(document_codes) > 1
    )
    duplicate_samples = []
    duplicate_groups = sorted(
        (
            (digest, document_codes)
            for digest, document_codes in content_documents.items()
            if len(document_codes) > 1
        ),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    for digest, document_codes in duplicate_groups[:25]:
        duplicate_samples.append(
            {
                "document_count": len(document_codes),
                "chunk_instance_count": content_hashes[digest],
                "document_codes": sorted(document_codes)[:20],
                "content_preview": content_previews[digest],
            }
        )
    duplicate_source_extra = sum(
        count - 1 for count in source_hashes.values() if count > 1
    )
    chunk_total = len(chunk_lengths)
    count_mismatch_documents = sum(
        item["chunk_count"] != item["observed_chunk_count"]
        for item in documents
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_dir.resolve()),
        "document_count": len(documents),
        "unique_source_sha256_count": len(source_hashes),
        "duplicate_source_extra_count": duplicate_source_extra,
        "chunk_count": chunk_total,
        "reported_chunk_count": quality_totals["chunk_count"],
        "chunk_count_mismatch_document_count": count_mismatch_documents,
        "malformed_jsonl_line_count": malformed_jsonl,
        "quality_totals": dict(quality_totals),
        "cross_document_exact_duplicate_extra_count": (
            exact_duplicate_extra
        ),
        "cross_document_exact_duplicate_rate": (
            exact_duplicate_extra / chunk_total if chunk_total else 0.0
        ),
        "cross_document_duplicate_samples": duplicate_samples,
        "low_information_chunk_count": low_information,
        "low_information_chunk_rate": (
            low_information / chunk_total if chunk_total else 0.0
        ),
        "low_information_samples": low_information_samples,
        "chunk_length": {
            "min": min(chunk_lengths, default=0),
            "median": median(chunk_lengths) if chunk_lengths else 0,
            "p95": percentile(chunk_lengths, 0.95),
            "max": max(chunk_lengths, default=0),
        },
        "largest_documents": sorted(
            documents,
            key=lambda item: item["chunk_count"],
            reverse=True,
        )[:10],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    quality = summary["quality_totals"]
    length = summary["chunk_length"]
    duplicate_rate = summary[
        "cross_document_exact_duplicate_rate"
    ] * 100
    low_info_rate = summary["low_information_chunk_rate"] * 100
    lines = [
        "# Batch ingestion quality summary",
        "",
        f"- Documents: {summary['document_count']}",
        f"- Unique source hashes: {summary['unique_source_sha256_count']}",
        f"- Chunks: {summary['chunk_count']}",
        f"- Empty chunks: {quality.get('empty_chunk_count', 0)}",
        f"- Mojibake chunks: {quality.get('mojibake_chunk_count', 0)}",
        f"- Filtered source chunks: "
        f"{quality.get('filtered_chunk_count', 0)}",
        f"- Within-document duplicate chunks: "
        f"{quality.get('duplicate_chunk_count', 0)}",
        f"- Cross-document exact duplicate extras: "
        f"{summary['cross_document_exact_duplicate_extra_count']} "
        f"({duplicate_rate:.2f}%)",
        f"- Low-information chunks: "
        f"{summary['low_information_chunk_count']} ({low_info_rate:.2f}%)",
        f"- Chunk length: min {length['min']}, median {length['median']}, "
        f"p95 {length['p95']:.1f}, max {length['max']}",
        "",
        "## Largest documents",
        "",
        "| Document | Chunks |",
        "|---|---:|",
    ]
    for item in summary["largest_documents"]:
        lines.append(
            f"| {item['document_code']} | {item['chunk_count']} |"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="汇总批量摄取的质量报告和切片指标。"
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = summarize(Path(args.input_dir))
    json_text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    markdown_text = render_markdown(summary)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json_text, encoding="utf-8")
    if args.markdown_output:
        output = Path(args.markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown_text, encoding="utf-8")
    print(markdown_text)


if __name__ == "__main__":
    main()

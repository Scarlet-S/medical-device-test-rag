import argparse
import json
import re
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    PROJECT_ROOT
    / "config"
    / "document_ingestion_manifest.fda_ai_validation_smoke20_v1.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "evaluation"
    / "fda_validation"
    / "fda_ai_validation_evaluation_v1.json"
)


def compact(text):
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"[#*_`|]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_section(markdown, heading_patterns):
    headings = list(re.finditer(r"(?m)^#{1,4}\s+(.+?)\s*$", markdown))
    for index, match in enumerate(headings):
        heading = compact(match.group(1))
        if not any(re.search(pattern, heading, re.I) for pattern in heading_patterns):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        content = compact(markdown[match.end() : end])
        if len(content) >= 80:
            return heading, content[:1200]
    return "", ""


def extract_header(markdown):
    fields = {}
    patterns = {
        "regulation_number": r"Regulation Number:\s*([^\n]+)",
        "regulation_name": r"Regulation Name:\s*([^\n]+)",
        "regulatory_class": r"Regulatory Class:\s*([^\n]+)",
        "product_code": r"Product Code:\s*([^\n]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, markdown, re.I)
        fields[key] = compact(match.group(1)) if match else ""
    return fields


def find_structured_path(document):
    source = Path(document["path"])
    output_root = Path(
        document.get("output_dir")
        or PROJECT_ROOT / "data" / "processed" / "fda_ai_validation_corpus_v1"
    )
    candidates = sorted(output_root.glob(f"{document['document_code']}__*/{document['document_code']}_structured.md"))
    if not candidates:
        candidates = sorted(
            (PROJECT_ROOT / "data" / "processed" / "fda_ai_validation_corpus_v1").glob(
                f"{document['document_code']}__*/{document['document_code']}_structured.md"
            )
        )
    if not candidates:
        raise FileNotFoundError(f"找不到结构化文件：{source.name}")
    return candidates[0]


def build_case(index, document):
    path = find_structured_path(document)
    markdown = path.read_text(encoding="utf-8")
    metadata = document.get("metadata", {})
    device = metadata.get("device") or document.get("title")
    filename = f"{document['document_code']}_structured.md"
    group = index // 5

    if group == 0:
        fields = extract_header(markdown)
        answer = (
            f"The decision summary identifies regulation number {fields['regulation_number']}, "
            f"regulation name {fields['regulation_name']}, regulatory class "
            f"{fields['regulatory_class']}, and product code {fields['product_code']}."
        )
        question = (
            f"In FDA 510(k) {metadata.get('submission_number')}, what regulation "
            f"number, regulation name, regulatory class, and product code are listed "
            f"for {device}?"
        )
        location = "510(k) decision letter header"
    elif group == 1:
        heading, answer = extract_section(
            markdown, [r"indications? for use", r"intended use"]
        )
        question = (
            f"According to FDA 510(k) {metadata.get('submission_number')}, what is "
            f"the stated intended use or indication for {device}?"
        )
        location = heading
    elif group == 2:
        heading, answer = extract_section(
            markdown,
            [r"clinical performance", r"non.?clinical performance", r"performance testing", r"verification and validation"],
        )
        question = (
            f"What performance or validation evidence is described for {device} "
            f"in FDA 510(k) {metadata.get('submission_number')}?"
        )
        location = heading
    else:
        heading, answer = extract_section(
            markdown,
            [r"software", r"algorithm", r"cybersecurity", r"device description"],
        )
        question = (
            f"What software, algorithm, or device-function information is described "
            f"for {device} in FDA 510(k) {metadata.get('submission_number')}?"
        )
        location = heading

    if not answer or not location:
        raise RuntimeError(
            f"{document['document_code']}未找到第{group + 1}组所需证据"
        )
    return {
        "question_id": f"F{index + 1:03d}",
        "expected_document": document["document_code"],
        "expected_filename": filename,
        "question": question,
        "expected_location": location,
        "reference_answer": answer,
    }


def main():
    parser = argparse.ArgumentParser(description="生成FDA案例库冻结检索评测集")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    documents = manifest["documents"]
    if len(documents) != 20:
        raise RuntimeError(f"本评测集要求20份文档，实际为{len(documents)}份")
    cases = [build_case(index, document) for index, document in enumerate(documents)]
    payload = {
        "metadata": {
            "title": "FDA AI医疗器械验证案例库检索评测集",
            "version": "v1",
            "created_date": date.today().isoformat(),
            "status": "FROZEN_AFTER_FIRST_RUN",
            "case_count": len(cases),
            "purpose": "验证20份FDA 510(k)决定摘要的精确文件召回、引用与回答质量。",
            "limitations": [
                "本题集仅用于新FDA案例库验收，不代表普遍监管要求。",
                "首次正式运行后不得依据本题集修改切片或提示词。",
            ],
        },
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"评测题数：{len(cases)}")
    print(f"输出：{args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

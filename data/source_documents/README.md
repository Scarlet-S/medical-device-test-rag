# Source Documents

This directory stores the original public documents used by the medical device software testing knowledge base.

Original files are not committed to GitHub because of file size, copyright, or licensing restrictions. Their metadata, official source URLs, regional applicability, file sizes, page counts, and SHA-256 values are recorded in:

- `data/catalog/document_catalog.csv`
- `data/catalog/document_integrity_v1.1.csv`

## Knowledge layers

### China regulatory layer

- `DOC001`-`DOC005`: the NMPA/CMDE source set used by project v1.0.
- `DOC006`: NMPA/CMDE usability engineering guidance (2024).
- `DOC007`: CMDE mobile medical device guidance (2025 revision).
- `DOC008`: NMPA product technical requirements guidance (2022).

These documents are Chinese official materials and are the primary source layer for questions about the Chinese regulatory environment.

### International reference layer

- `DOC009`: FDA premarket submissions for device software functions (2023).
- `DOC010`: FDA medical device cybersecurity guidance (2026).
- `DOC011`: FDA off-the-shelf software guidance (2023).

These documents are English U.S. FDA guidance. They are used only for international comparison and supplemental engineering ideas. They must not be presented as Chinese regulatory requirements.

### Project-authored practice layer

Practical testing guides are stored separately in `data/practice_documents`. They translate general lifecycle and risk-control concepts into executable test methods, evidence lists, and exit criteria. They are project-authored engineering references, not regulations or standards.

## Version and evaluation protection

The v1.0 five-document corpus, 50-question baseline, and 30-question holdout results remain frozen. New v1.1 documents must not overwrite historical evaluation artifacts. Reports must show old-corpus regression results separately from new-document results.

## Ingestion rules

1. Upload one document at a time.
2. Preserve the document ID at the beginning of the RAGFlow filename.
3. Confirm parser completion and inspect representative chunks before continuing.
4. Keep China regulatory, international reference, and project practice layers distinguishable by filename and metadata.
5. Do not use unofficial translations to replace English FDA originals.
6. Do not upload copyrighted consensus-standard full text unless a lawful copy and usage permission are available.
7. When sources conflict, answers about China must prioritize the current Chinese official source and identify foreign guidance as comparison only.

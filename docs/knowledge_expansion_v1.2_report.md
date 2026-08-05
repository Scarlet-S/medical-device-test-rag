# Knowledge expansion v1.2 report

Initial ingestion date: 2026-07-27
DOC014 cleanup date: 2026-08-04

## Active logical documents

| ID | Document | Active source form | RAGFlow parser | Chunks |
|---|---|---|---|---:|
| DOC012 | YY/T 0664—2020 medical-device software lifecycle processes | Local structured Markdown transcription | General (`naive`) | 35 |
| DOC013 | GB/T 42062—2022 medical-device risk management | Local structured Markdown transcription | General (`naive`) | 70 |
| DOC015 | Medical Device Adverse Event Monitoring and Re-evaluation Provisions | Official SAMR PDF | Laws (`laws`) | 28 |
| DOC016 | Provisions for Administration of Medical Device Recall | Official SAMR PDF | Laws (`laws`) | 39 |

## DOC014 removal decision

DOC014 (GB/T 38634 software-testing series) was removed from the active
knowledge base and from the current evaluation scope. The available source was
image-based, and the partial transcription was not complete enough to support
reliable clause-level retrieval or answer evaluation. Keeping incomplete
material would create a larger quality risk than omitting it from this
portfolio project.

The official 100-question expansion workbook does not depend on DOC014. It
retains coverage of DOC012, DOC013, DOC015, and DOC016, so removing the obsolete
DOC012-DOC014 incremental set does not invalidate the current reported metrics.

## Quality and evidence controls

- Active source files completed parsing and indexing with no empty chunks.
- DOC012 and DOC013 were manually reviewed after structured transcription.
- DOC015 was repaired after parsing: a page-header-only chunk was removed and
  the split Article 80 heading was merged with the preceding context.
- Original or transcribed standards are not redistributed in this repository.
- Clause-level conclusions must be verified against an authorized copy of the
  applicable standard.
- Chinese official regulations remain the primary evidence layer for questions
  about the Chinese regulatory environment.

## Current evaluation evidence

The frozen official expansion evaluation contains 100 questions. After the
document and answer-quality repair workflow, the final retrieval result was
88/100 strict Top-1 and 92/100 strict Top-3. The calibrated judge result was
99/100 automatic citation correctness, 183/200 answer accuracy, and 1/100
automatic hallucination; documented manual adjudication produced 100/100
citation correctness and 0/100 hallucination while retaining 183/200 answer
accuracy.

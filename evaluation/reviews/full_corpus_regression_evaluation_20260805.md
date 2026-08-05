# Full-corpus regression evaluation — 2026-08-05

## Scope

The final active RAGFlow corpus contains 30 physical file entries representing
23 logical sources:

- 15 official or standards-based logical documents (`DOC001`-`DOC013`,
  excluding removed `DOC014`, plus `DOC015` and `DOC016`);
- 8 project-authored engineering-practice documents
  (`PRACTICE001`-`PRACTICE008`);
- `DOC010` is stored as eight physical Markdown volumes, which accounts for
  the difference between logical sources and RAGFlow file entries.

The complete evaluation portfolio contains 204 questions. Each question uses
an independent chat session and preserves the answer, ordered references,
similarity values, and scoring output.

## Frozen retrieval configuration

- Similarity threshold: `0.20`
- Vector/full-text weight: `0.50 / 0.50`
- Top N: `8`
- Rerank: `qwen3-rerank`
- Top-K: `128`
- Cross-language search: disabled
- Default chat timeout: 30 seconds; two persistent slow questions were retried
  once with a temporary 60-second process-level override.

## Retrieval results

| Evaluation set | Questions | Success | Strict Top-1 | Strict Top-3 |
|---|---:|---:|---:|---:|
| DOC001-DOC005 baseline regression | 50 | 50/50 | 39/50 (78.0%) | 49/50 (98.0%) |
| DOC001-DOC005 former holdout regression | 30 | 30/30 | 27/30 (90.0%) | 29/30 (96.7%) |
| Official expansion regression | 100 | 100/100 | 88/100 (88.0%) | 92/100 (92.0%) |
| Engineering-practice regression | 24 | 24/24 | 24/24 (100%) | 24/24 (100%) |
| **Combined** | **204** | **204/204** | **178/204 (87.3%)** | **194/204 (95.1%)** |

The 24 practice questions also achieved 24/24 exact-filename Top-1 and Top-3
hits.

## Automatic judge results

| Evaluation set | Citation correctness | Answer accuracy | Hallucination |
|---|---:|---:|---:|
| DOC001-DOC005 baseline regression | 50/50 | 96/100 | 1/50 |
| DOC001-DOC005 former holdout regression | 30/30 | 58/60 | 0/30 |
| Official expansion regression | 99/100 | 183/200 | 1/100 |
| Engineering-practice regression | 24/24 | 45/48 | 0/24 |
| **Combined raw automatic result** | **203/204 (99.5%)** | **382/408 (93.6%)** | **2/204 (1.0%)** |

## Manual adjudication

Manual review was restricted to low-score and judge-disagreement cases. It did
not change genuine omissions.

- Baseline Q008: the additional user-testing relationship was directly
  supported by retrieved evidence, so it was not a hallucination and the core
  answer was complete.
- Baseline Q045: product-specific examples were directly supported and did not
  make the complete core answer inaccurate.
- Former holdout H018: the judge's explanation explicitly concluded that all
  required points were present but still emitted accuracy `1`; this internal
  contradiction was corrected to `2`.
- Expansion E053: the answer correctly stated that retrieved evidence did not
  directly establish the requested requirement; the judge improperly inferred
  a generic maintenance-plan requirement.
- Expansion E090: the omitted reporting party justified accuracy `1`, but the
  additional regulator reporting detail had direct evidence and was not a
  hallucination.

After adjudication:

| Metric | Final manually adjudicated result |
|---|---:|
| Citation correctness | **204/204 (100%)** |
| Answer accuracy | **385/408 (94.4%)** |
| Hallucination | **0/204 (0%)** |

## Evidence files

Retrieval inputs:

- `batch_eval_50_full_regression_doc001_doc005_merged_final_20260804_165745.json`
- `batch_eval_30_full_regression_holdout_doc001_doc005_final_20260804_171738.json`
- `batch_eval_100_official_expansion_v1_topk128_qwen_repaired_final_20260804_143221.json`
- `batch_eval_24_practice_documents_v1_full_20260805_111142.json`

Judge outputs:

- `judge_eval_50_20260804_170338.json`
- `judge_eval_30_20260804_172237.json`
- `judge_eval_100_official_expansion_v1_topk128_qwen_repaired_final_20260804_143504.json`
- `judge_eval_24_20260805_111428.json`

Runtime JSON and CSV outputs remain local under `evaluation/results/` and are
excluded from Git. This report records the reproducible filenames and aggregate
metrics without publishing potentially large local result artifacts.

## Interpretation and limitations

- Strict document-code Top-1 penalizes legitimate overlap between documents
  such as DOC003 and DOC004; Top-3 and citation correctness better represent
  whether the assistant received usable evidence.
- The original 30-question holdout set is now a regression set because it was
  previously used for system analysis.
- The practice set is a coverage regression set for project-authored material,
  not an independent generalization benchmark and not evidence of regulatory
  compliance.
- Results depend on the frozen local corpus, current external model services,
  and retry policy. Timeout retries replace transport failures only and do not
  alter retrieval configuration or answer content.

# 07 — Extraction Evaluation

**Status:** Evaluation strategy still largely open. No pharmaceutical accuracy
dataset, field-level acceptance threshold, or reviewer-effort study exists yet.
An early **Materials lexical feasibility** measurement was recorded under L09
(resource/stability evidence only — not content accuracy).

Owner of extraction-quality and reviewer-effort evaluation. Software unit/integration tests: [02_code_quality_standards.md](02_code_quality_standards.md). Check-specific value measurement: [08_check_selection_strategy.md](08_check_selection_strategy.md). Product hypotheses: [00_project_reference.md](00_project_reference.md).

---

## 0. L09 early full-Materials feasibility (2026-09-28)

Read-only measurement helper: `tests/lexical_extraction/acceptance.py`. Uses
accepted L03→L08 APIs unchanged. Component `materials` only; fuzzy disabled; no
publication. Post-run integrity boundary (same date, reporting correction): hash
or sidecar failures use `status=integrity_failed` with
`HTML_INPUT_CHANGED` / `KNOWLEDGE_WRITE_DETECTED`; HTML-only changes do not set
`knowledge_write_detected`. Historical A/B JSON values below were not rewritten.

| Item | Value |
|------|-------|
| Host | MSI MS-7D25; Windows 11 Pro 10.0.26200; Python 3.11.4; ~128 GiB RAM |
| Declared peak-process budget | 32 GiB (`windows_psapi_peak_working_set`) |
| Reviewed HTML v1 | provenance export revision `f489826a-37bc-45e8-a13c-b648caf28b27`; 158,317 bytes; 18 pages / 728 blocks; SHA-256 `e38333226b2beb96a01a4566233064a2e399beabb6e92bd63eeca25f46e2f7d5` |
| Snapshot | `flat-v1-a39c0b393ffdbd4e97ed`; DB 441,327,616 bytes; SHA-256 `cd709652a4b4de5acf9ca8558a2423fb3e8ebf83e0fde5994cca47af922468f2` |
| Fixed limits | batch 5000; cache 65536 KiB; max term codepoints/shard 50_000_000; result buffer 50_000 |
| Configured shard settings | A: `max_terms_per_shard=500_000`; B: `2_000_000` (separate processes). Configured values differed; **actual effective shard counts were not measured**. |
| Eligible terms | 4,345,238 (both runs) |
| Raw discoveries / occurrences / candidates / blocks | 4,058 / 472 / 4,058 / 728 |
| Semantic digest | `b785ba207f6442b2736593eb93472af4bd6ad8f8627703b034e1345448290f5c` (identical A/B) |
| Peak WS | A 502,824,960 bytes; B 503,087,104 bytes (both under budget) |
| Match+aggregation time | A ~162.9 s; B ~163.7 s |
| Input/snapshot integrity | hashes unchanged; no WAL/SHM/journal; no knowledge write |
| Unavailable metrics | temporary spool peak bytes; indexing/search/aggregation phase split; effective shard counts |

Reports: `out/lexical-l09/run-a-shard-500000.json`,
`out/lexical-l09/run-b-shard-2000000.json`. Not pharmaceutical accuracy, not
manual extraction acceptance, not a final extraction manifest.

---

## 1. What to measure

| Area | Intent |
|------|--------|
| Entity/field precision and recall | Against annotated reference data |
| Relationships and ordering | Correct step–material/equipment links; process ordering where asserted |
| Numerics | Values, units, ranges; prescribed-versus-observed distinctions |
| Evidence | Evidence-location correctness; unsupported assertions |
| Missing/ambiguous coverage | Omissions must not artificially inflate accuracy |
| Human effort | Correction/review time and end-to-end effort vs the same manual task |
| Supporting ops metrics | Processing time and cost per document |

Model confidence is **not** measured correctness. There is **no** single established "90% accuracy" metric yet. The ~85% effort-reduction figure is likewise a hypothesis requiring defined metrics.

---

## 2. Denominators, matching, and tolerance

Design must define:

- What counts as a true positive / false positive / false negative for each field type
- Entity matching rules (string normalization, synonyms, identifiers)
- Numeric and unit tolerances
- How prescribed vs observed mismatches are scored
- How missing/ambiguous reference annotations affect denominators

Exact matching/tolerance choices: **OPEN**.

---

## 3. Representative sampling

Sample across:

- Master vs executed records
- Digital vs scanned pages
- Layout variety and table complexity
- Difficult values (ranges, dual units, handwritten/noisy OCR where in scope)

Synthetic or public examples may support initial development but do **not** establish real-customer performance. No confidential customer dataset is assumed available.

Keep explicit:

- Reference annotation process
- Ambiguous-source adjudication rules
- Evaluation-set versioning
- Separation of evaluation samples from development/tuning samples

Exact sample counts and numerical thresholds: **OPEN**.

---

## 4. Comparative evaluations

| Comparison | Purpose |
|------------|---------|
| BOM/LOE-assisted extraction vs without | Measure quality impact of document-local references |
| Optional catalog/RAG enrichment vs without | Measure gains and **unsupported additions** |
| Graph-assisted review vs structured-only review | Task completion and effort when UI exists |

Use comparable documents and outcomes for fair comparison.

---

## 5. What does not count as extraction accuracy

- Unit tests with fake model output ([02](02_code_quality_standards.md), [04](04_code_map.md))
- Manual anecdotes without an evaluation set
- Aggregate "accuracy" without defined fields and denominators
- Check pass rates alone ([08](08_check_selection_strategy.md))

Code tests verify software behavior. This document owns extraction-quality and reviewer-effort measurement.

---

## 6. Open decisions

- Evaluation-set composition and sample counts
- Annotation guidelines and adjudication process
- Matching/tolerance rules per field type
- Numerical acceptance or regression thresholds (if any)
- Whether/when customer documents enter evaluation under NDA/process controls
- Effort-study protocol for reviewer time measurement

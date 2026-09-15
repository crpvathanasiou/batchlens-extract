# 07 — Extraction Evaluation

**Status:** Evaluation strategy to define. No extraction dataset, accuracy result, or acceptance threshold exists yet unless independently confirmed locally (none confirmed for this repository).

Owner of extraction-quality and reviewer-effort evaluation. Software unit/integration tests: [02_code_quality_standards.md](02_code_quality_standards.md). Check-specific value measurement: [08_check_selection_strategy.md](08_check_selection_strategy.md). Product hypotheses: [00_project_reference.md](00_project_reference.md).

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

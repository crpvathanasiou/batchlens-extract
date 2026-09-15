# 08 — Check Selection Strategy

**Status:** Selection framework. No final check inventory, fixed weights, or implementation order is approved.

Owner of how checks are selected and prioritized, including Extract vs Audit ownership. Data availability: [05_pipeline_contracts.md](05_pipeline_contracts.md). Validation of check value: [07_extraction_evaluation.md](07_extraction_evaluation.md). Product boundaries: [00_project_reference.md](00_project_reference.md).

---

## 1. Selection dimensions

| Dimension | Question |
|-----------|----------|
| User time saved | Does this remove meaningful manual work? |
| Frequency | How often does the issue appear in target documents? |
| Source-data availability | Is required evidence usually present in the PDF/result? |
| Consequence | What happens if a finding is missed or wrong? |
| False-positive / review burden | How often will reviewers dismiss noise? |
| Implementation and maintenance effort | Cost to build and keep correct? |
| Verifiability | Can we measure that the check works ([07](07_extraction_evaluation.md))? |

Use qualitative reasoning initially. Do **not** invent weighted scores or population statistics.

---

## 2. Candidate record (compact)

For each candidate check, record:

| Field | Content |
|-------|---------|
| Purpose | What user problem it addresses |
| Owner | **Extract** (structural / document consistency) or **Audit** (regulatory / process-rule) |
| Required evidence | What must exist in source or structured result |
| Applicability | When the check is in scope |
| Expected benefit | Qualitative user-value hypothesis |
| Implementation effort | Qualitative cost |
| Evaluation method | How success/failure of the check itself is measured |
| Unresolved questions | What must be decided before implementation |

---

## 3. Ownership: Extract vs Audit

| Owner | Appropriate checks |
|-------|--------------------|
| **Extract** | Provenance completeness, structural validation, internal document consistency (e.g., BOM/LOE vs body) |
| **Audit** | Compliance against an applicable approved specification or regulatory/process rule |

Internal document consistency ≠ regulatory validity. Do **not** implement Audit regulatory evaluation inside Extract.

---

## 4. Outcome semantics

- Missing evidence → unresolved / not-evaluable when appropriate — **not** an automatic pass or failure.
- Severity, execution blocking, and review status are **separate** decisions.
- No scoring scheme may cancel a critical finding by accumulating unrelated passes.
- Automatic unreviewed delivery remains allowed: findings and uncertainty can travel with an explicit unreviewed result ([05](05_pipeline_contracts.md)).

---

## 5. Proposed examples (not approved rules)

Clearly marked **PROPOSED EXAMPLE** only — not selected design and not a committed inventory.

### Example A — BOM materials without identified step usage

**Owner (proposed):** Extract
**Idea:** Flag BOM materials that never appear in step usage.
**Caution:** Requires applicability context; not automatically a violation (some materials may be listed for other reasons).

### Example B — Equipment in steps but absent from detected LOE

**Owner (proposed):** Extract
**Idea:** Flag equipment referenced in steps but missing from a detected LOE.
**Caution:** The LOE itself may be incomplete or serve a different purpose.

### Example C — Numeric/unit inconsistencies across related entries

**Owner (proposed):** Extract
**Idea:** Flag inconsistent values/units across related source entries.
**Caution:** Requires valid shared context and correct unit interpretation.

---

## 6. Initial set guidance

Select a **small valuable** initial set after evidence model and pipeline design ([05](05_pipeline_contracts.md)). Do **not** impose an arbitrary 5–10-check requirement. Do **not** shrink useful extraction scope solely to satisfy the first checks.

---

## 7. Open decisions

- Initial check inventory and implementation order
- Severity and blocking policy per check
- Whether any scoring/aggregation is used (and how critical findings are protected)
- Applicability rules for BOM/LOE-related consistency checks
- Which candidates, if any, belong to Audit instead of Extract
- Evaluation protocol per selected check ([07](07_extraction_evaluation.md))

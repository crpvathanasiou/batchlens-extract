# 05 — Pipeline Contracts

**Status:** Document conversion and optional human review **are implemented** in code (not production-qualified). L01 lexical record contracts **are implemented** and **test-verified**; they are not a working extractor. Parsing, search, monitoring, and publication remain **unimplemented**. Rules/Audit evaluation and a persistent audit ledger are **not implemented**. Broader extraction orchestration remains **OPEN**.

Primary owner of pipeline responsibilities, data semantics, and lifecycle invariants. Product boundaries: [00_project_reference.md](00_project_reference.md). Engineering errors: [02_code_quality_standards.md](02_code_quality_standards.md). Check selection: [08_check_selection_strategy.md](08_check_selection_strategy.md). Security of artifacts: [06_security_and_data_handling.md](06_security_and_data_handling.md).

---

## 1. Design responsibilities (conceptual)

These are responsibilities to design, **not** a locked execution sequence or deployment topology.

| Responsibility | Intent |
|----------------|--------|
| Intake / source preservation | Accept manufacturing PDFs; retain original bytes and identity/revision metadata |
| Document / page preparation | Render or OCR pages as needed; produce workable page/text representations |
| Reference-section identification | Locate BOM/LOE (and similar) sections wherever they appear |
| Entity / relationship extraction | Extract materials, equipment, operations/steps, usages, parameters, limits |
| Reconciliation / validation | Compare extracted content to document-local references; emit consistency findings |
| Result assembly | Build versioned structured result with evidence, uncertainties, and findings |
| Optional review | Human inspection/correction without erasing provenance of prior machine output |

---

## 2. Conceptual data inventory

Design concepts — **not** existing classes or finalized JSON fields.

| Concept | Meaning |
|---------|---------|
| Source document and revision | Original PDF (or equivalent) and its document/revision identity where known |
| Processing run | One attempt to process a source into a result |
| Recipe representation | Structured recipe/batch content derived from the source |
| Materials | Substances/items identified in the document |
| Equipment | Equipment items identified in the document |
| Operations / steps | Unit operations and ordered or unordered process steps |
| Contextual material/equipment usage | Use of a material or equipment **in a particular step/context** |
| Parameter observations / limits | Values, ranges, units, and limits bound to a step/context |
| Evidence references | Pointers into the source sufficient to explain an assertion |
| Findings | Document-consistency or structural-validation outcomes (not Audit compliance) |
| Review revisions | Human corrections layered on a machine (or prior) result |

### Contextual binding (invariant)

A quantity belongs to a particular use/context. A temperature or speed belongs to a particular step/context. Do **not** collapse all occurrences into one material or equipment property.

---

## 3. Information meanings that must stay distinguishable

| Kind | Meaning |
|------|---------|
| Missing | Expected information was not found |
| Ambiguous | Multiple interpretations remain plausible |
| Conflicting | Sources disagree |
| Prescribed | Instruction, limit, or target stated by the document |
| Observed | Recorded execution value or deviation |
| Normalized | Transformed representation (e.g., unit conversion) with traceable link to source |
| Externally enriched | Added from catalog/RAG or other non-document sources (optional; must be labeled) |

When normalization occurs, preserve source values/units alongside the transformation trail.

Executed-record extraction produces an evidence-based recipe representation; it does **not** establish the authoritative master recipe ([00](00_project_reference.md)).

---

## 4. BOM / LOE and evidence rules

- Use BOM/LOE sections wherever present as document-local references for extraction and reconciliation.
- Preserve materials/equipment found elsewhere even when absent from those sections.
- Reconciliation can reveal omissions or mismatches; it **cannot** establish regulatory validity or completeness independently of the source.
- A missing reference section must not force custom Excel transcription as a product requirement.
- Evidence must support **relationships** as well as entities.
- Uncertain ordering must not be invented from proximity alone.

---

## 5. Processing, review, and findings (meanings)

Describe meanings without locking enum names or a complete transition table.

| Concern | Meaning |
|---------|---------|
| Processing completion | Pipeline finished producing a result artifact for the run |
| Partial output | Usable subset exists; some expected content missing or incomplete |
| Technical failure | Unrecoverable operational failure; distinct from data-quality findings |
| Review status | Whether a human has inspected/corrected (e.g., explicitly unreviewed in automatic mode) |
| Check / finding outcomes | Results of structural or consistency checks |

**Approved automatic mode:** return a usable result with uncertainty and an **explicit unreviewed** status. Missing evidence or uncertainty is not automatically a pass, a technical failure, or a mandatory human-review stop.

Human review may govern approval or consequential actions; it must not universally prevent automatic draft delivery.

Keep **operational errors** (engineering failures) distinct from **data-quality findings**. Error engineering rules: [02](02_code_quality_standards.md). Check selection: [08](08_check_selection_strategy.md).

---

## 6. Provenance, replay, and views

- Store references sufficient to explain outputs and corrections.
- Fixed configuration and temperature do **not** guarantee identical future LLM outputs.
- Distinguish **deterministic** projection/check replay from **rerunning** probabilistic extraction. Exact mechanisms: **OPEN**.
- Tabular and graph views use the **same versioned result**, with evidence links and synchronized corrections.
- Graph nodes/edges are generated deterministically from the versioned model — not a separate LLM reconstruction.
- Neo4j / GraphRAG: not required ([00](00_project_reference.md)).

### Future audit ledger (APPROVED TARGET / not implemented)

Initial persistence target, recorded as direction only — **no implementation in current work**:

- One canonical append-only JSON Lines audit ledger, for example `.audit/audit-events.jsonl`, under a persistent application-data directory.
- The ledger must remain outside source control and Docker images.
- Operational logs remain structured stdout logs, not another persistent audit file ([02](02_code_quality_standards.md) §14.5).
- Future audit events should store references, IDs, hashes, revision links, actors, times, actions, and outcomes — not duplicate full PDFs or complete JSON artifacts.
- A future AWS/Azure adapter should persist the same canonical event schema as append-only events or rows.
- A hash chain can be tamper-evident, but is not proof of tamper-proof storage or 21 CFR Part 11 compliance.

---

## 7. Extract vs Audit boundary

Extract owns extraction, provenance, structural validation, and document-consistency findings.

Audit (separate planned tool) owns regulatory/process-rule evaluation over compatible structured input, including from other sources.

Shared versioned contract schema and deployment separation: **OPEN**.

---

## 8. Open decisions

- Detailed stage inputs/outputs and orchestration order for **pharmaceutical extraction**
- Identifiers and serialization for recipe/result assembly beyond the L01 lexical records
- Exact lifecycle transition names for run control, retry, and resume (L01 outcome labels are settled below; the run state machine is not)
- Versioning mechanism for **extracted** results beyond `batchlens.lexical-record.v1` (document-review revisions are implemented in code; see [04](04_code_map.md))
- Retry / resume behavior after partial extraction failure
- Extract–Audit contract fields and versioning
- First demonstrable end-to-end **extraction** slice scope
- Audit-ledger event schema (direction in §6; implementation deferred)

These remain purposes of remaining **M-Design** work after intended-use / regulatory-boundary and audit/provenance design ([01](01_implementation_roadmap.md), [03](03_common_handoff.md)). Conversion and review contracts already exist in code and must not be silently redesigned here.

---

## 9. L01 lexical records (implemented contracts, not an extractor)

Code: `src/app/lexical_extraction/contracts.py`. Schema `batchlens.lexical-record.v1`.
A small synthetic fixture is `examples/lexical_extraction/result-example.json`.
Validation is by bounded records (input, page, block, occurrence, outcome, publication).
There is no production model that must hold every page and match at once.

**Input.** After successful validation, reviewed HTML v1 requires `html_sha256`, contract
version 1, and the producer root metadata: `job_id`, `review_revision_id`, `review_generation`,
and `conversion_status` (the HTML `data-job-id`, `data-review-revision-id`,
`data-review-generation`, and `data-conversion-status` values). An external document id may be
absent. A failure before that validation has no validated-input record and must not invent those
fields.

**Evidence.** A page has a positive physical page number, order, and coverage. A block keeps
its node id, structural kind, exact text (empty text is valid), page membership, order,
optional element/table/cell geometry, and original ordered OCR references (an empty list is
valid). A match span is a zero-based half-open Unicode code-point range with nonempty
`matched_text`. Standalone span checks do not prove the slice. `validate_match_against_block`
requires `block.text[start:end] == matched_text` and does not normalize text. Overlapping spans
are kept. Later ordering is by page order, block order, then span start/end and occurrence id.
This module does not sort or dedupe.

**Candidates.** A finalized dictionary occurrence has at least one source-backed candidate.
FDA/EMA and ChEBI stay separate. FDA/EMA search fields are `material_name`, `alias_name`, and
`UNII`; ChEBI search fields are `material_name` and `alias_name`. CAS numbers are not search
fields. `SMS_ID` and `CHEBI_ID` are identities, not search fields. Those column rules do not
filter Material aliases by language. Equipment matching excludes dedicated Greek fields, brand,
manufacturer, model, manufacturer/model ids, and Published range. Dedicated Greek fields are
also outside the Unit Operations matching boundary. Missing native ids do not
invalidate a source row. Generic cues have no operation id. `Index this row` is source text on
the unit-operation candidate and does not gate a process-step candidate. A parameter candidate
may carry catalogue equipment scope; that is not a detected equipment mention. Match methods are
exact, normalized exact, and fuzzy, with fixed rule ids. Exact evidence must equal the
occurrence text. Normalized-exact does not apply normalization here. Fuzzy evidence is one
alphabetic word of at least six characters and a recorded edit distance of 0 or 1; the
distance is not calculated. Phrases are not fuzzy. Fuzzy is rejected for chemicals, UNII, and
units. Ambiguity (`none`, `unresolved`, `context_required`) is not a technical failure.

**Units and values.** A unit mention has its own literal, span, rule, and either the fixed unit
vocabulary or an `equipment.Unit` row. The literal must equal the span text on the mention
itself. It has no parameter name, `parameter_id`, or equipment identity. Value forms are
scalar-with-unit, range, comparison, symmetric tolerance, categorical, and cued unitless.
`raw_expression` equals the expression span. A recorded source unit requires a unit span with
the same text, and that span lies inside the expression. A number–unit group lies inside the
expression, and its number and unit spans lie inside the group. Numbers are exact finite
decimal strings, or an explicit ambiguous token with no resolved value. Grouping is syntactic.
Each value occurrence records rule `lexical-v1-value`. One value occurrence may apply to both
quantity and parameter-value components without a second copy and without a parent entity.

**Outcomes.** Components are `unit_operations`, `process_steps`, `materials`, `equipment`,
`parameter_names`, `units`, `quantity_expressions`, and `parameter_value_expressions`. Requested
presets are a separate list from directly requested components and from resolved components.
Presets are not expanded here. Run provenance also stores a supplied internal-rules SHA-256
beside `lexical-internal-rules-v1`; L01 does not compute that digest. Every resolved component
has exactly one outcome and cannot be
`not_requested`. A component outside that selection may be absent or `not_requested`, and cannot
claim executed work. `not_requested` carries no counts.
`completed` includes a measured count, and zero is a real empty result. `partial` keeps usable
results with an explicit count. `failed` requires a safe structured error. An all-failed
requested run is `failed`, not `completed` or `partial`. Completed component results may sit
inside an overall `partial`. Unavailable measurements are omitted, not stored as zero.

**Publication.** Completed publication requires a final-manifest claim. Failed or interrupted
publication must not carry that claim. Partial extraction may be paired with completed
publication. The claim does not prove that files were written.

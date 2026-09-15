# 05 — Pipeline Contracts

**Status:** Approved semantic requirements; detailed contract design **OPEN**; pipeline **not implemented**.

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

---

## 7. Extract vs Audit boundary

Extract owns extraction, provenance, structural validation, and document-consistency findings.

Audit (separate planned tool) owns regulatory/process-rule evaluation over compatible structured input, including from other sources.

Shared versioned contract schema and deployment separation: **OPEN**.

---

## 8. Open decisions

- Detailed stage inputs/outputs and orchestration order
- Identifiers and serialization formats (including JSON schemas)
- Evidence location format (page/region/text span/other)
- Exact lifecycle transition names and allowed transitions
- Versioning mechanism for results and review revisions
- Retry / resume behavior after partial failure
- Extract–Audit contract fields and versioning
- First demonstrable end-to-end slice scope

These are purposes of **M-Design** after D2 review ([01](01_implementation_roadmap.md)). They remain open during documentation initialization.

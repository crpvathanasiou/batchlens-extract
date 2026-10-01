# BatchLens — L03: Reviewed HTML v1 Reader and Evidence Mapping

## 1. Authorization and stop boundary

L01 contracts and L02 execution configuration/preset resolution have been accepted by the user. Implement **L03 only**: read a reviewed HTML v1 export, validate its producer and structural provenance, and expose its physical pages and source blocks through the existing L01 evidence records. Add focused tests and update the execution-state documentation.

Stop after the L03 completion report. Do not implement snapshot access, catalogue field mapping, matching or normalization, fuzzy logic, values, aggregation, runner/CLI, monitoring, or result publication. Do not start L04.

## 2. Accepted baseline and local inspection

Repository: `C:\Users\User\batchlens-extract`. Inspect the actual working tree before editing. The supplied L02 report recorded 19 configuration tests, 38 combined lexical tests, and a passing 308-test repository gate; these are **reported** results, not a substitute for your own checks. The user has now accepted L02; reflect that change in the current handoff.

Read, in order:

1. `AGENTS.md`, `.ai/03_common_handoff.md`, relevant `.ai/02_code_quality_standards.md`, `.ai/01_implementation_roadmap.md`, `.ai/04_code_map.md`, and `.ai/05_pipeline_contracts.md`.
2. `src/app/lexical_extraction/contracts.py`, `configuration.py`, their focused tests, and the current package layout.
3. `src/app/document_review/rendering.py`, its `README.md`, and `tests/document_review/test_rendering.py`, especially the root/page/node attributes, nested articles, tables, empty cells, generated regions, `<br>`, and OCR reference tests. Inspect the actual producer code rather than inferring behavior from example HTML.
4. `pyproject.toml`, `poetry.lock`, and `scripts/quality.ps1` for existing parsing dependencies and the supported quality gate.
5. A newly exported **reviewed HTML v1** sample if one is available locally. A historical conversion `document.html` is not this input. The detailed lexical handoff is supporting context if locally available; this prompt and the accepted L01/L02 contracts define this task.

Do not modify the review renderer to make the reader easier to implement.

## 3. Input and output boundary

The sole content input is the exact reviewed HTML file bytes, optionally reached via `EffectiveExecutionConfiguration.input.reviewed_html_path`. Expose a small public reader boundary taking a `Path` (and, if helpful, a thin adapter for that config path). It should return/produce:

- A `ReviewedHtmlV1Input` **only for a successfully validated input**, containing SHA-256 of the exact bytes consumed, strict version `1`, required producer `job_id`, `review_revision_id`, `review_generation`, and `conversion_status`. An external document ID may remain absent.
- Physical pages in source DOM order as existing `PageRecord` objects containing `PageEvidence` and `BlockRecord`/`BlockEvidence`, with empty occurrence tuples. Keep the API page-oriented/iterable; do not require a whole-document Pydantic tree or hold all pages and blocks in memory.
- A bounded, explicit input/read/contract error with a stable code or equivalent structured failure that a later runner can map to the L01 error/outcome records. A failure before successful validation has no fabricated `ReviewedHtmlV1Input` or guessed producer metadata.

Make validation/completion semantics unambiguous for a page iterator: a caller must not claim successful complete coverage or finalized input identity if it stops early or a late parse/hash error occurs. Hash the bytes actually parsed; if implementation uses separate passes, detect input changes between passes before reporting success. Do not open a PDF or document JSON as a fallback. Do not require SQLite, a network resource, or an output directory.

## 4. Reader behavior

Use a real HTML parser, never regex for HTML parsing. Do not execute scripts or fetch external resources. Decode valid UTF-8 and HTML entities once; turn `<br>` into `\n`; keep all other source whitespace exactly, including leading/trailing spaces, blank text, Unicode combining characters, and carriage returns that occur in the reviewed text. Do not include HTML indentation outside source blocks. `BlockEvidence.text` is the original evidence string used by later code-point span checks, not normalized text.

Validate the root `<html data-review-html-version="1">` and all producer-required attributes. Reject legacy/unsupported version, missing/invalid metadata, invalid UTF-8, invalid/malformed source-bearing structure, or source text that cannot be faithfully represented. Attributes alone do not prove independent approval or authenticity. Report the failure; do not silently mark partial content complete.

Read **every** physical `section.page` with a valid positive `data-page`, preserving DOM order and the physical page number. Do not assume page numbers are contiguous or derived from a printed label. Check page identity (`id="source-page-N"` as produced), duplicate physical pages, and duplicate block node IDs. A valid empty page and valid empty source block remain represented. Page `coverage=complete` means all supported HTML source blocks on that physical page were read; it does not claim the original PDF/OCR conversion was complete. In particular, the root may say `PARTIAL_SUCCESS` while a faithfully read HTML page has complete HTML coverage.

Skip a node **and all its descendants** when it carries `data-generated="true"`; also exclude head/style/script and navigation/tool UI. Preserve genuine source headings, titles, table captions, paragraphs, footers, table cells, repeated literal text, and contents/appendix pages. Each supported `data-node-id` text-bearing node becomes **exactly one** block; never scan an enclosing `article.element` or `<table>` again to duplicate its child blocks. Preserve page/block order and keep distinct cells separate, without joining text across blocks.

Carry the exact `data-node-id`; the owning `article.element` `data-element-id`/`data-kind` where applicable; `data-table-id` on cells; cell row/column/span geometry and header status as supported by the existing L01 fields; and node-local ordered `data-source-id` OCR references (missing references remain empty, never inherited from a parent). Use one stable, documented mapping to `BlockEvidence.kind`, including standalone title/heading/footer/cell blocks, without expanding the L01 schema solely to add an HTML parser abstraction. Honor producer nesting and require relevant structural attributes where missing values would silently lose identity or location.

**Known provenance limitation:** the renderer joins original OCR `block_id` values into `data-source-id` with spaces, but an existing renderer test allows an original `block_id` that itself contains a space (`"blk a"`). That case is not reversibly decodable from the HTML attribute alone. Implement the documented v1 token interpretation for ordinary IDs in order, preserve missing references, and explicitly record this limitation in the L03 report/docs. Do not claim that a split attribute proves the original ID grouping, do not invent an alternate PDF/JSON lookup, and do not silently change the producer or L01 contracts within L03. If the local producer has changed or this ambiguity blocks faithful handling of the actual acceptance sample, report the concrete evidence and stop for review.

No mention detection occurs in L03. Do not emit dictionary occurrences, units, values, candidate identities, or zero-result extraction claims. The later matcher will use zero-based half-open Unicode code-point offsets in each `BlockEvidence.text`.

## 5. Permitted changes

Create a focused reader module such as `src/app/lexical_extraction/html_reader.py` and its focused tests such as `tests/lexical_extraction/test_html_reader.py`. A tiny synthetic reviewed HTML fixture may live under the focused tests if useful. Update `src/app/lexical_extraction/__init__.py` only for a small public re-export if consistent with existing practice.

Update `.ai/03_common_handoff.md`, `.ai/04_code_map.md`, `.ai/05_pipeline_contracts.md`, and a concise `.ai/01_implementation_roadmap.md` status entry as applicable. Record the accepted L02 baseline, actual L03 result and checks, the reader API and provenance semantics, the OCR ID limitation, and remaining unimplemented work. Keep `.ai/03_common_handoff.md` the execution-state anchor; do not create a competing project history.

Avoid touching L01/L02 contracts/configuration, the renderer or review UI/API, existing document conversion, flat SQLite, snapshot companions, source CSVs, or unrelated tests. Prefer existing/standard parsing facilities; a narrowly justified direct dependency change is permissible only if needed for faithful bounded parsing, with a scoped lock change and explanation. Do not add a generic framework.

## 6. Meaningful verification

Focused synthetic tests should cover:

1. Exact root metadata and SHA-256 of source bytes; required metadata/version failure and invalid UTF-8; no validated-input claim on failure.
2. Multiple physical pages, DOM ordering, noncontiguous page numbers where valid, an empty page, an empty cell, and duplicate/invalid page or node identities.
3. Generated ancestor and page label exclusion alongside genuine source heading, caption, footer, nested child, table cells, and repeated text inclusion **once** per node.
4. `<br>`, escaping/entities, literal leading/trailing whitespace, non-ASCII Unicode/combining marks, original code-point slicing, and no cross-cell text merging.
5. Correct article/table ownership, cell coordinates/spans, node-local OCR reference order, and absent references. Document/test the exact semantics used for space-delimited OCR IDs; do not claim round-trip recovery for IDs containing spaces.
6. Missing structural provenance, unsupported or silently dropped source-bearing elements, malformed nesting/closure, truncated input, and early iterator close versus completion; an error must not be reported as a complete document.
7. No reads of PDF/JSON/SQLite, no file creation during reading, and unchanged existing rendering behavior.

Where practical, build fixtures through the existing renderer or mirror its exact v1 markup in small readable fixtures; do not add brittle assertions on incidental CSS. If the newly exported reviewed HTML is available to Cursor, perform a **read-only** smoke check of page count, node count, SHA-256, a title/footer and a table cell (including a literal text slice), and report whether this was programmatic or manually inspected. A reviewed HTML v1 sample supplied outside the Cursor filesystem must not be assumed to exist there; state its absence rather than substituting original-conversion HTML. This smoke check is parser/evidence acceptance, not material extraction or human pharmaceutical validation.

Run focused reader tests, combined lexical tests, and the applicable full repository gate (`scripts/quality.ps1` in the supported environment). Report actual commands, outcomes, and blocks. Do not weaken gates, rewrite unrelated tests, or assert historical counts as current.

## 7. Definition of Done and completion report

L03 is done when a later matcher can consume correctly ordered `PageRecord`/`BlockEvidence` from valid reviewed HTML v1 and a trustworthy validated-input identity from the **same bytes**, while invalid or incomplete input yields an explicit failure rather than fabricated provenance or falsely complete coverage. It remains possible to highlight later by the saved node ID and offsets in the exact block text. Existing application behavior stays unchanged.

Return:

1. Exact files changed and public reader API, including page iteration/validation-completion semantics.
2. Attribute-to-evidence mapping, exclusion/text handling, SHA-256 calculation, and explicit error behavior.
3. Focused and full-gate commands/results, plus reviewed HTML sample check if available; separate test-verified from manually verified.
4. The `data-source-id` whitespace limitation and any other concrete unresolved finding.
5. Documentation changes and remaining L04+ boundaries.

**Stop after L03. Await review and explicit user acceptance before any L04 work or prompt.**

# 03 — Common Handoff

## 1. Current state — 2026-09-30 Stage 3 U1–U3 local workspace complete

**Mini-project:** Stage 3 — Extraction Review Workspace.

**Status:** **implemented**, **test-verified**, and **manually verified** for the
local U1–U3 vertical slice under `src/app/extraction_review/`,
`src/app/api/extraction_reviews.py`, the Vue extraction-review workspace, and
`tests/extraction_review/local_harness.py`.

### Boundaries

- Stage 2 remains the independent deterministic Lexical Extraction Engine
  (`src/app/lexical_extraction/`). Stage 3 opens completed local Stage 2/L13 jobs;
  it does not redesign lexical extraction.
- Stage 1 source-document approval is separate and unchanged.
- One final human action only: **Approve extraction result**. No page, component,
  lexical, LLM, finding, or automatic approval.
- Current-state-only review: one saved finding list, immutable source/run binding,
  one `current_revision_id` (stale Save detection), optional current approval.
  Effective Save clears approval; approval covers committed content only.
- No review revision history, approval ledger, version list, SQLite review store,
  or automatic merge/transfer of edits between runs.
- Findings keep lexical origin/evidence and user add/change/remove provenance.
  Removal is a restoreable tombstone. A user-added finding is assigned to the
  current page by the By-page UI; it has `no_document_evidence` and no invented
  document-evidence node, block, span, or highlight.

### Per-run isolation

A Stage 3 current review belongs to one `LocalLexicalJob`, keyed by `local_job_id`:

```text
<data-dir>/extraction-reviews/<sha256(local_job_id)>/current-review.json
```

Two completed runs of the same approved HTML have independent saved/approved
states. Binding still verifies the exact published run/manifest within that local
job. Old source-`job_id` keyed local review files were not migrated. This is not a
duplicate-upload, execution-fingerprint, cache/reuse, or run-history system.

### U2 local execution

- **U2.1** discovers eligible reviewed HTML under the approved-documents root.
- **U2.2** persists local background lexical jobs and raw L13 runs; one active
  writer/worker per data directory; reload/restart recovery with truthful terminal
  status.
- Harness `--run-extraction` validates the selected approved HTML, submits and waits
  for a Stage 2 run, then opens the Stage 3 UI with `initialLocalJobId`. A run is
  never automatically approved.

### Accepted Stage 2 lexical facts (unchanged engine)

Search includes canonical names and searchable aliases; canonical-name matches take
precedence over aliases; one deterministic candidate per exact component/block/span;
one displayed occurrence per `(page, component, casefolded matched text)`; components
remain independent; `hasRelatedSynonym` aliases are searchable; short literals under
three code points and `context_required` UO terms stay excluded; per-page de-duplication
buffering is bounded by `result_buffer_records`. Page classification / page-policy
exclusion remain future work.

### Accepted local UI / API / harness

- Left: read-only reviewed HTML page with category-distinct lexical highlights.
- Right: findings. By page is editable; All findings is read-only and navigates to
  the finding’s page. Add is By-page only and assigns the current page.
- Edit, Remove, Restore, Save, Download TXT, and final approval as implemented.
- TXT exports active saved findings by category/document order; removed findings
  excluded; no-evidence additions marked.
- Category legend (UO / Material / Equipment / Other) hides/shows that category on
  both sides; session-only; does not dirty Save; no API call. Finding selection
  focuses/navigates evidence only.
- Selector labelled **Extraction run** (not document); distinguishes runs with
  action, status, finished time when available, and local-job suffix.
- `--run-extraction` passes `initialLocalJobId` so first load and refresh open that
  exact run.

Local harness API (not production-mounted): list/open jobs, page HTML, save, approve,
results TXT under `/api/v1/extraction-reviews/...`.

### Manual acceptance (local slice)

Completed for: manual add → Save → final approval; refresh persistence; TXT download;
post-approval Save clears approval; same approved HTML with two lexical runs keeps
independent reviews and approvals.

### Explicitly out of this mini-project

Production API mounting/authentication; page classification; duplicate-upload /
fingerprint / reuse workflows; LLM; graph/associations; recipe assembly; automatic
approval; Stage 1 or Stage 2 redesign.

**Next safe step:** treat Stage 3 local U1–U3 as accepted baseline. Do not expand into
production mount/auth, page classification, fingerprint/reuse, LLM, or graph work
without a new authorized task.

---

## 1ae. Prior current state — 2026-09-28 L13 streaming-reader correction

**Implemented** focused L13 streaming-reader correction only: compacting UTF-8
JSON buffer, complete envelope / page_count validation, and honest
early-close drain of page block iterators. Writer, CLI exits, manifest-last /
partial publication, output-path guard, short-write hashing, and L01–L12
behavior are unchanged. Review UI was **not** started. The 169.257 s full
real-input report remains historical evidence for older publisher code and does
**not** verify this reader.

- `_Utf8JsonStream` uses one incremental UTF-8 decoder across byte chunks;
  invalid UTF-8 fails with `ARTIFACT_UTF8`. Consumed text is compacted after
  each token so retained buffer length does not scale with previously parsed
  pages/blocks (`peak_retained_chars` observed).
- After `pages` closes, the reader requires the root `}`, only trailing
  whitespace through EOF, and `page_count` equal to pages yielded. Leading /
  trailing commas and truncated envelopes fail closed with structured codes.
- `StreamedComponentPage.iter_blocks()` always finishes the underlying block
  stream in `finally` (including early `close()`), so the next page parses from
  a correct offset; `drained` reports completion.

**Test-verified:** focused `tests/lexical_extraction/test_publication.py`
**26 passed**; combined `tests/lexical_extraction/` **278 passed**;
`scripts/quality.ps1` passed — Ruff check, Ruff format check (102 files already
formatted), Pyright 0 errors / 0 warnings / 0 informations, pytest **548 passed**.

**L12 status:** **user-accepted** baseline for L13.
**L13 status (historical note):** streaming-reader corrected, **implemented** and
**test-verified** here; later **user-accepted** with the Stage 2 engine used by
Stage 3 (see current §1).
**Next safe step (historical):** user review of corrected L13.

---

## 1ad. Prior current state — 2026-09-28 L13 bounded publication / exact lookup correction

**Implemented** focused L13 correction only: bounded page/block staging and
streaming artifact write/read, checked write-all with hash-from-published-file,
exact `locate_hit` span matching, and snapshot-path output guard. Accepted
L01–L12 matching/config/snapshot/runner behavior and L13 CLI exit codes /
manifest-last / partial publication semantics are unchanged. Review UI was
**not** started. Later corrected again for compacting UTF-8 reader / envelope
validation (see current §1). The prior 169.257 s full real-input report remains
historical evidence for the pre-correction publisher, not verification of later
reader fixes.

- Staging keeps finite counters only (`page_count`); page index / last block
  order live in per-page `.meta` files. Blocks must arrive in ascending
  `(order, node_id)` (fail-closed); materialization streams one validated block
  at a time without assembling a `PageRecord` or all-block list.
- Component artifact writes use a checked write-all loop; descriptor size/SHA-256
  come from the completed temporary file before atomic replace. Injected short
  writes fail closed with no committed artifact.
- `iter_component_pages` / `open_component_artifact_stream` parse the JSON
  incrementally (header then one page/block value at a time); never
  `json.loads` the whole file. `locate_hit` returns only on an exact occurrence
  span match (including nested value/unit spans); wrong span / empty block →
  `None`.
- `guard_output_outside_snapshot` / sink `begin_run` refuse
  `output.directory` equal to or inside the snapshot (resolved containment)
  before creating any run directory. `publish_lexical_run` applies the same
  guard.

**Test-verified (historical):** focused `tests/lexical_extraction/test_publication.py`
**22 passed**; combined `tests/lexical_extraction/` **274 passed**;
`scripts/quality.ps1` passed — Ruff check, Ruff format check (102 files already
formatted), Pyright 0 errors / 0 warnings / 0 informations, pytest **544 passed**.

**L12 status:** **user-accepted** baseline for L13.
**L13 status (historical note):** corrected, later streaming-reader corrected
(prior §1ae); later **user-accepted** with Stage 3 (see current §1).
**Next safe step (historical):** user review of corrected L13.

---

## 1ac. Prior current state — 2026-09-28 L13 CLI and atomic lexical-result publication

**L12 acceptance:** user explicitly authorized L13 on the accepted L01–L12 baseline
(including the L12 bounded-count / sink-lifecycle correction). L12 is now
**user-accepted**.

**Implemented** L13 only: filesystem `EvidenceSink` publication, thin CLI module
entry, atomic per-component artifacts, and final-manifest-last sealing. Accepted
L01–L12 matching/config/snapshot/runner behavior is unchanged. Review UI, finding
approval, vector/LLM retrieval were **not** started. Later corrected for bounded
serialization/lookup/write/path guard and streaming-reader fixes (prior §1ad/§1ae);
later **user-accepted** with Stage 3 (see current §1).

- `src/app/lexical_extraction/publication.py`: `FilesystemEvidenceSink` stages
  page skeletons and blocks under `{output.directory}/{run_id}/.staging/` with
  bounded per-page files; supports concurrent provisional components (L10 shared
  composition); `complete_component` atomically commits
  `artifacts/component-<name>.json`; `complete_run` seals only;
  `finalize_publication(result)` writes `manifest.json` last after outcome/
  artifact agreement. Partial extraction may publish completed publication with
  only completed-component artifacts. Failed/interrupted publication leaves no
  completed publication claim.
- `src/app/lexical_extraction/__main__.py`:
  `poetry run python -m app.lexical_extraction --config <execution.yaml>`.
  Exit codes: `0` completed+published, `1` partial+published, `2` failed
  extraction / pre-validation, `3` publication or CLI/config failure. Compact
  summary prints run id, statuses, per-component counts/error codes, peak memory,
  manifest path — no source block text.
- Reader helpers: `load_final_manifest`, `verify_artifact_hashes`,
  `iter_component_pages`, `locate_hit`.
- Compatible L12 note: `EvidenceSink` docstring clarifies concurrent provisional
  component streams for L10 (behavior already used by the runner).

**Test-verified (historical):** focused `tests/lexical_extraction/test_publication.py`
**17 passed**; combined `tests/lexical_extraction/` **269 passed**;
`scripts/quality.ps1` passed — Ruff check, Ruff format check (102 files already
formatted), Pyright 0 errors / 0 warnings / 0 informations, pytest **539 passed**.

**Real-input E2E (historical programmatic; not human manual acceptance; not
verification of later bounded-publication or streaming-reader corrections):**
`full` preset, fuzzy OFF, L09 limits (batch 5000 / cache 65536 KiB /
`max_terms_per_shard=2_000_000` / max term codepoints 50_000_000 / buffer 50_000).
HTML revision `f489826a-37bc-45e8-a13c-b648caf28b27` SHA-256
`e38333226b2beb96a01a4566233064a2e399beabb6e92bd63eeca25f46e2f7d5`; snapshot
`flat-v1-a39c0b393ffdbd4e97ed` DB SHA-256
`cd709652a4b4de5acf9ca8558a2423fb3e8ebf83e0fde5994cca47af922468f2`. Before/after
HTML+DB+manifest hashes unchanged; no WAL/SHM/journal sidecars. Run
`5af7a352-8ed5-4621-b829-d8025b5eb870`; elapsed **169.257 s**; peak process memory
**506,093,568** bytes (`windows_psapi_peak_working_set`). Counts:
unit_operations 62, process_steps 9, materials 472, equipment 0,
parameter_names 4, units 87, quantity_expressions 55,
parameter_value_expressions 55; extraction/publication `completed`; exit 0.
All eight artifact SHA-256/size verified; 472 materials spans validated against
published block text; three sample page/node/span locations matched original HTML
slices (programmatic highlight-location usability). **Not** pharmaceutical
precision/recall; review UI still unimplemented.

**L12 status:** **user-accepted** baseline for L13.
**L13 status:** **implemented** and **test-verified**; later corrected (see
current §1); still **awaiting user acceptance**.
**Next safe step (historical):** user review of L13 publication/CLI.

---

## 1ab. Prior current state — 2026-09-28 L12 bounded-count and sink-lifecycle correction

**Implemented** focused L12 correction only: bounded eligible-row counting, streamed
component-scoped page emission without an all-page retained list, and truthful
sink finalization that preserves committed component outcomes. Accepted L01–L11
matching/config/snapshot behavior and selected-component extraction are unchanged.
Units remain non-fuzzy. L13 / CLI / final manifest / review UI were **not** started
at that date (implemented later as prior §1ac / current §1).

- `EligibleTermCounter` counts eligible rows with a previous `(table, row_id)` key
  and an integer; no retained set of row IDs. Rows that emit no terms are not
  counted.
- HTML validation counts pages/blocks without retaining `_PageMeta` for every page.
  Each component streams page skeletons from a fresh L03 reader; empty pages and
  identity checks are preserved. Incomplete/changed page replay fails the component.
- `EvidenceSink.write_page(component, page)` is component-scoped. Combined L10 runs
  emit each component's ordered pages exactly once.
- L10 `complete_component` failure aborts only uncommitted components; already
  completed siblings stay completed (overall `partial`).
- `complete_run` failure keeps validated HTML/snapshot identities and committed
  outcomes, sets additive `LexicalRunResult.run_error`, and calls `abort_run`
  without retracting committed components. No completed publication claim.

**Test-verified (historical):** focused `tests/lexical_extraction/test_runner.py`
**16 passed**; combined `tests/lexical_extraction/` **252 passed**;
`scripts/quality.ps1` passed — Ruff check, Ruff format check (99 files already
formatted), Pyright 0 errors / 0 warnings / 0 informations, pytest **522 passed**.

**L11 status:** user-accepted baseline for L12.
**L12 status:** corrected, later **user-accepted** as L13 baseline (see current §1).
**Next safe step (historical):** user review of corrected L12. Do not start L13.

---

## 1aa. Prior current state — 2026-09-28 L12 callable extraction runner

**Implemented** L12 only: callable bounded runner composing accepted L02–L11 into
one run boundary, with a caller-owned evidence sink, honest per-component /
overall outcomes, `RunProvenance` when identities are known, and compact
in-memory operational monitoring. Later corrected for bounded counts and sink
lifecycle (see current §1).

- Public API: `run_lexical_extraction(config, sink)` and optional
  `run_lexical_extraction_from_config_path`; sink lifecycle
  `begin_run` → `begin_component` → provisional `write_page` /
  `write_block` → `complete_component` / `abort_component` →
  `complete_run` / `abort_run`.
- Failure boundaries: shared HTML validation + one snapshot preflight; each of
  `unit_operations` / `process_steps` / `materials` / `equipment` is an
  independent L05→L07→L08 pass; selected L10 components share one L10 composition
  (no duplicate parameter/value output).
- HTML is fully validated before search; snapshot prefights once; streams close
  on success, failure, and early abort. Zero-hit components complete with count 0
  only after full stream success. Independent completed components remain usable
  under overall `partial`.
- Monitoring records observed pages/blocks, completed/failed/zero-result
  components, matches by component/method, eligible terms/rows and candidates when
  measured, stage timings, configured limits, and peak process memory when a
  supported nonprivileged method is available (otherwise unavailable).
- Logs stay structured and small (`run_id`, stage/component, status, counts,
  elapsed, error code); no document text or unrestricted paths.

**Test-verified (historical):** focused `tests/lexical_extraction/test_runner.py`
**12 passed**; combined `tests/lexical_extraction/` **248 passed**;
`scripts/quality.ps1` passed — Ruff check, Ruff format check (99 files already
formatted), Pyright 0 errors / 0 warnings / 0 informations, pytest **518 passed**.

**Real-input smoke:** not run (no local reviewed HTML v1 export + production
snapshot pair present for a bounded L12 smoke in this workspace).

**L11 status:** user-accepted baseline for L12 (including both fuzzy-evidence
corrections).
**L12 status:** **implemented** and **test-verified**; later corrected (see
current §1); still **awaiting user acceptance**.
**Next safe step (historical):** user review of L12. Do not start L13, CLI,
final-manifest publication, or the review UI.

---

## 1z. Prior current state — 2026-09-28 L11 edge-whitespace fuzzy validation correction

**Implemented** focused L11 correction only: observed fuzzy span normalization no
longer strips edges in `dictionary_aggregation.py` and `fuzzy_matching.py`, plus
focused regressions. Accepted L01–L10 behavior and prior L11 fuzzy rule/eligibility/
OFF default remain unchanged. Units stay non-fuzzy. L12 was then implemented (see
current §1).

- Forged oversized spans such as `" Presure"` / `"Presure "` against `Pressure`
  fail closed (`FUZZY_OBSERVED_NOT_WORD`) with no aggregation coverage.
- Inner word span `[1, 8)` on block `" Presure "` still yields
  `FuzzyEvidence(edit_distance=1)` with exact original offsets.
- Prior rejections (`Fil ter`, `Filter!`, interior boundary failures, strict
  integer distance) and genuine `Presure` behavior stay in force.

**Test-verified (historical):** focused `tests/lexical_extraction/test_fuzzy_matching.py`
**17 passed**; combined `tests/lexical_extraction/` **236 passed**;
`scripts/quality.ps1` passed — Ruff check, Ruff format check (96 files already
formatted), Pyright 0 errors / 0 warnings / 0 informations, pytest **506 passed**.

**L10 status:** user-accepted baseline for L11.
**L11 status:** edge-whitespace corrected; later **user-accepted** as L12 baseline
(see current §1).
**Next safe step (historical):** user review of corrected L11. Do not start L12.

---

## 1y. Prior current state — 2026-09-28 L11 fuzzy evidence validation correction

**Implemented** focused L11 correction in `dictionary_aggregation.py` and
`fuzzy_matching.py`, plus focused regressions in
`tests/lexical_extraction/test_fuzzy_matching.py`. Accepted L01–L10 behavior and
L11's fixed one-edit rule, eligibility, OFF default, and exact/normalized path are
unchanged. Runner/CLI, publisher, monitoring, review UI, and L12 remain
**unimplemented**.

- L08 fuzzy validation now requires an exact integer `edit_distance=1` (booleans
  rejected), one alphabetic observed comparison word within one-edit length of the
  eligible source key, and — during block replay — literal slice equality plus the
  source term's fixed L06 boundary against `block.text`. Injected `Fil ter`,
  `Filter!`, and interior `Presure` in `xPresure` fail closed with no coverage.
- Signature-resource test charges deletion signatures meaningfully: a limit above
  exact-only reference cost but below reference+signature cost succeeds with
  `fuzzy_enabled=False` and fails `OVERSIZED_TERM` with fuzzy ON.

**Test-verified (historical):** focused
`tests/lexical_extraction/test_fuzzy_matching.py` **16 passed**; combined
`tests/lexical_extraction/` **235 passed**; `scripts/quality.ps1` passed — Ruff
check, Ruff format check (96 files already formatted), Pyright 0 errors /
0 warnings / 0 informations, pytest **505 passed**.

**L10 status:** user-accepted baseline for L11.
**L11 status:** corrected, **implemented** and **test-verified**; later corrected
again for edge whitespace (see current §1); still **awaiting user acceptance**.
**Next safe step (historical):** user review of corrected L11. Do not start L12.

---

## 1x. Prior current state — 2026-09-28 L11 optional restricted fuzzy dictionary matching

**Implemented** in `src/app/lexical_extraction/` as L11-only additive fuzzy support on
the existing dictionary path: `fuzzy_matching.py`, plus minimal compatible changes to
`dictionary_matcher.py`, `dictionary_aggregation.py`, and `parameter_unit_value.py`.
L01–L10 remain the accepted baseline. L02's user-facing configuration schema is
unchanged. Runner/CLI, publisher, monitoring, review-UI projection, and L12 remain
**unimplemented**.

- Optional callable `fuzzy_enabled` (default `False`) on `iter_raw_discoveries` and
  the L10 parameter-name seam. OFF preserves exact/normalized-exact outputs and does
  not build fuzzy state. ON adds fixed V1 ordinary Levenshtein distance-1 hits only.
- Eligibility: L05 `fuzzy_allowed` plus fixed role/policy gates. Fuzzy only for
  single alphabetic natural-language words ≥6 Unicode code points (equipment type,
  parameter name, unit operation, independently eligible process step). Materials,
  chemicals/UNII, units, generic/context/support/inspection/step-cue terms,
  abbreviations, phrases, and equipment codes/models stay non-fuzzy.
- Candidate retrieval uses a per-shard deletion-signature index over eligible L06
  comparison keys, then exact distance verification. Signature storage is charged
  against `max_term_codepoints_per_shard` (fail closed / shard split; no truncation).
- `RawDiscovery` carries optional `edit_distance`; L08 revalidates eligibility and
  recomputes distance before emitting L01 `FuzzyEvidence`. Precedence:
  `exact` > `normalized_exact` > `fuzzy`. Units/values remain non-fuzzy.

**Test-verified (historical):** focused
`tests/lexical_extraction/test_fuzzy_matching.py` **15 passed**; combined
`tests/lexical_extraction/` **234 passed**; `scripts/quality.ps1` passed — Ruff
check, Ruff format check (96 files already formatted), Pyright 0 errors /
0 warnings / 0 informations, pytest **504 passed**.

**L10 status:** user-accepted baseline for L11.
**L11 status:** **implemented** and **test-verified**; later corrected (see
current §1); still **awaiting user acceptance**.
**Next safe step (historical):** user review of L11. Do not start L12.

---

## 1w. Prior current state — 2026-09-28 L10 value-only reviewed-HTML replay correction

**Implemented** focused correction in `parameter_unit_value.py` and focused L10
tests only. L01–L09 production behavior is unchanged. Historical L09 reports are
retained. Fuzzy matching, runner/CLI, monitoring, review-UI projection, and
publication remain **unimplemented**.

- Value-only runs (`quantity_expressions` / `parameter_value_expressions`
  without parameter or unit streams) may use a fresh `ReviewedHtmlBlockReplay`
  with a caller-supplied expected full-file SHA-256. Blocks stream without an
  all-document buffer; the unpinned first pass is allowed only in that case.
  Finalized replay identity is verified **after full consumption** before
  coverage is published. Wrong digest, read failure, or early close yields an
  explicit failure / `STREAM_INCOMPLETE` with no completed coverage.
  Already-pinned sources keep immediate identity checks.
- Prior L10 bounded lockstep stream, per-block `result_buffer_records`, unit
  provenance/normalization, and early-close cleanup remain in force.

**Test-verified:** focused `tests/lexical_extraction/test_parameter_unit_value.py`
**18 passed**; combined `tests/lexical_extraction/` **219 passed**;
`scripts/quality.ps1` passed — Ruff check, Ruff format check (94 files already
formatted), Pyright 0 errors / 0 warnings / 0 informations, pytest **489 passed**.

**L09 status:** user-accepted baseline for L10.
**L10 status:** value-only replay corrected, **implemented** and
**test-verified**; later accepted as L11 baseline (see current §1).
**Next safe step (historical):** user review of corrected L10. Do not start L11.

---

## 1v. Prior current state — 2026-09-28 L10 bounded-stream and unit/value evidence correction

**Implemented** correction in L10 modules only:
`parameter_unit_value.py`, `unit_aggregation.py`, `value_expressions.py`,
`unit_value_rules.py`, plus focused tests. L01–L09 production behavior is
unchanged. Historical L09 reports are retained. Fuzzy matching, runner/CLI,
monitoring, review-UI projection, and publication remain **unimplemented**.

- Block stream composes ordered L08 dictionary blocks, L10 unit blocks, and
  per-block value recognition incrementally (lockstep). No whole-document
  discovery/result dictionaries. Equipment unit terms for dual unit/value use
  are retained only under explicit finite bound `_MAX_EQUIPMENT_UNIT_TERMS`
  (fail closed). Parameter/unit term streams feed L07 without an intermediate
  unbounded `list(...)`.
- `result_buffer_records` bounds **per-block** discoveries/occurrences.
  Cumulative counts remain coverage-only. Unit aggregation and the L10 stream
  set coverage only after successful full consumption **and** spool/stream
  cleanup.
- Equipment `Unit` discoveries require a pinned L04 snapshot + L05 mapping;
  fixed vocabulary does not. Dual fixed+equipment hits keep controlled
  spelling/identity and deterministic representative `supporting_row_ids` /
  `Source / section`. Exact fixed + normalized-exact equipment coexistence no
  longer raises `EXACT_EVIDENCE_MISMATCH` for case-only alternatives.
- Value unit recognition is casefold-consistent with L06/L07 while preserving
  exact source substrings (`120 RPM` → controlled `rpm`). Identifier-prefixed
  range/tolerance tails and embedded cues (`MaxSpeed:`) are rejected.

**Test-verified (historical):** focused
`tests/lexical_extraction/test_parameter_unit_value.py` **17 passed**; combined
`tests/lexical_extraction/` **218 passed**; `scripts/quality.ps1` passed —
Ruff check, Ruff format check (94 files already formatted), Pyright 0 errors /
0 warnings / 0 informations, pytest **488 passed**.

Earlier real-HTML smoke (fixed vocabulary only) remains historical smoke only
and was not re-run as an L09-style Materials benchmark in this correction.

**L09 status:** user-accepted baseline for L10.
**L10 status:** corrected, **implemented** and **test-verified**; still
**awaiting user acceptance**.
**Next safe step:** user review of corrected L10. Do not start L11.

---

## 1u. Prior current state — 2026-09-28 L10 independent parameter names, units, and values

**Implemented** in `src/app/lexical_extraction/` as L10-only modules plus one
minimal L01 additive contract field. L01–L09 remain the accepted baseline (L09
measurement/helper integrity boundary included). Fuzzy matching, runner/CLI
product surface, monitoring, review-UI projection, and publication remain
**unimplemented**.

- Public entry points: `iter_parameter_unit_value_block_records` and
  `recognize_block_values` in `parameter_unit_value.py`. Parameter names reuse
  L05→L07→L08 without selecting or detecting equipment. Units use L07 plus L10
  `unit_aggregation` (L08 still rejects unit discoveries). Values use
  `value_expressions.recognize_value_expressions`.
- Fixed V1 rules/vocabulary in `unit_value_rules.py`
  (`lexical-unit-value-rules-v1` / `lexical-unit-vocabulary-v1`): quantity units
  such as `kg`, `g`, `mg`, `µg`/`ug`, `L`, `mL`/`ml`, `µL`/`uL`/`ul`, `%`, `°C`/`C`,
  `°F`/`F`, `K`, `Pa`, `kPa`, `bar`, `atm`, `mol`, `mmol`, `IU`, `CFU`, `rpm`,
  `min`, `s`, `h`; categoricals `OFF` and `under vacuum`; cue `Speed:`.
- Compatible contract change: optional `supporting_row_ids` on
  `EquipmentUnitRecord` (default empty) so repeated equipment-unit rows retain
  references without multiplying one textual hit.
- Component selection suppresses unrequested output. Value selection may
  recognize a unit inside an expression without emitting `UnitOccurrence` unless
  `units` is selected. Both value components together emit once with both
  `applies_to` values. No entity association is asserted.

**Test-verified** in the initial L10 pass: focused
`tests/lexical_extraction/test_parameter_unit_value.py` **12 passed**; combined
`tests/lexical_extraction/` **213 passed**; `scripts/quality.ps1` passed — Ruff
check, Ruff format check (94 files already formatted), Pyright 0 errors /
0 warnings / 0 informations, pytest **483 passed**.

**Optional real-HTML smoke (not a substitute for tests; not L09-style full
measurement):** reviewed HTML v1
`.local-review-data/html-provenance-20260925/.../document.html` (SHA-256
`e38333226b2beb96a01a4566233064a2e399beabb6e92bd63eeca25f46e2f7d5`), components
`units` + both value components, fixed vocabulary only (no equipment snapshot
terms): **18 pages / 728 blocks**, **86** unit occurrences, **54** value
occurrences. Marked smoke only; not pharmaceutical content validation.

Bounded-stream / unit-evidence corrections followed in current §1.

---

## 1t. Prior current state — 2026-09-28 L09 integrity reporting boundary correction

**Implemented** correction in `tests/lexical_extraction/acceptance.py` and focused
helper tests only. Accepted L01–L08 production modules were **not** changed.
Historical L09 A/B Materials measurement JSON under `out/lexical-l09/` is retained
unchanged as recorded evidence; this pass did **not** rerun full Materials.

- Post-run integrity: changed reviewed-HTML or snapshot companion/database hashes,
  or a detected SQLite WAL/SHM/journal sidecar, yield
  `status=integrity_failed` with stable codes `HTML_INPUT_CHANGED` or
  `KNOWLEDGE_WRITE_DETECTED`. Those reports must not claim completed integrity.
- HTML-only hash change does **not** set `knowledge_write_detected=true`.
  Snapshot hash change or sidecar does.
- `compare_measurement_digests` requires both sides to claim completed integrity
  (`status=completed`, `hashes_unchanged=true`, no knowledge write, no
  `error_code`); integrity-failed reports cannot compare as success.

**Shard-setting precision (prior L09 A/B evidence):** configured
`max_terms_per_shard` differed (500,000 vs 2,000,000). Actual effective shard
counts were **not measured** and must not be inferred from the configured limits
alone. Digests/counts matched across those configured settings.

**Prior L09 real measurement (historical, observed values unchanged):** see §1s.
Helper remains the recorded early-feasibility path; pharmaceutical content
validation was out of scope for L09.

**Test-verified** in this integrity-boundary correction: focused
`tests/lexical_extraction/test_acceptance.py` **11 passed**; combined
`tests/lexical_extraction/` **201 passed**; `scripts/quality.ps1` passed — Ruff
check, Ruff format check (89 files already formatted), Pyright 0 errors /
0 warnings / 0 informations, pytest **471 passed**.

**L09 status at that date:** measurement recorded; helper integrity boundary
**implemented** and **test-verified**. Per L10 authorization, L01–L09 are now the
accepted baseline (see current §1).

---

## 1s. Prior current state — 2026-09-28 L09 early full-Materials feasibility measurement

**Implemented** read-only measurement helper `tests/lexical_extraction/acceptance.py`
with focused synthetic tests. Accepted L01–L08 production modules were **not**
changed. L09 is a measurement/acceptance task, not another extraction engine.
Fuzzy matching, value parsing, unit aggregation, runner/CLI product surface,
monitoring, review-UI projection, and publication remain **unimplemented**.
Integrity reporting was corrected in the following pass (current §1).

- Helper path: finalize L03 HTML identity → open L04 snapshot → L05 Materials
  terms (`materials_fda_ema` + `materials_chebi`, including UNII under the fixed
  L05 rule) → L07 `iter_raw_discoveries` → L08 `iter_aggregated_block_records`.
  Fuzzy stays disabled. Streaming semantic digest over emitted `BlockRecord`
  values; full result tree is not retained. Peak process memory uses Windows
  `GetProcessMemoryInfo` (`windows_psapi_peak_working_set`). Temporary L08 spool
  peak size and indexing/search/aggregation phase splits are recorded as
  **unavailable** (would require instrumenting accepted modules).
- Declared peak-process-memory budget before runs: **32 GiB**
  (`34359738368` bytes), justified by host ~128 GiB physical RAM and ~93–95 GiB
  free at measurement time (MSI MS-7D25 / Windows 11 Pro / Python 3.11.4).

**Real measurement inputs (local):**

- Reviewed HTML v1:
  `.local-review-data/html-provenance-20260925/objects/local-fexofenadine/revisions/f489826a-37bc-45e8-a13c-b648caf28b27/exports/document.html`
  (158,317 bytes; L03 pages **18** / blocks **728**; SHA-256
  `e38333226b2beb96a01a4566233064a2e399beabb6e92bd63eeca25f46e2f7d5`).
  Conversion `document.html` was **not** substituted.
- Snapshot:
  `C:\Users\User\Desktop\MBR_core\RAG-Core-data\Agregate-Items\Prepared\flat-sqlite\flat-v1-a39c0b393ffdbd4e97ed`
  (`snapshot_id` `flat-v1-a39c0b393ffdbd4e97ed`; database 441,327,616 bytes;
  SHA-256 `cd709652a4b4de5acf9ca8558a2423fb3e8ebf83e0fde5994cca47af922468f2`).

**Two complete Materials measurements** (separate processes; other resource
limits held fixed at L02 defaults except configured `max_terms_per_shard`).
Configured values differed; **actual effective shard counts were not measured**.

| Setting | configured `max_terms_per_shard` | Preflight s | Match+agg s | Total s | Peak WS bytes | Baseline WS |
|---|---:|---:|---:|---:|---:|---:|
| A | 500,000 | 2.755 | 162.901 | 166.413 | 502,824,960 (~480 MiB) | 39,550,976 |
| B | 2,000,000 | 2.659 | 163.672 | 167.096 | 503,087,104 (~480 MiB) | 39,309,312 |

Shared stable counts/digest (both runs): eligible terms **4,345,238**; raw
discoveries **4,058**; blocks emitted **728**; dictionary occurrences **472**;
candidates **4,058**; semantic digest SHA-256
`b785ba207f6442b2736593eb93472af4bd6ad8f8627703b034e1345448290f5c`. Peak memory
was under the 32 GiB budget (`budget_exceeded=false`). HTML/database/manifest/
validation-report/contract hashes unchanged before/after; no WAL/SHM/journal
sidecars; no knowledge write; no publication claim. OS cache notes: remeasure
runs after earlier warm passes (file cache likely warm). JSON reports under
`out/lexical-l09/` (historical observed values retained).

This is **early feasibility**, not pharmaceutical content validation, final
end-to-end extraction, or manual review acceptance of extracted Materials.

**Test-verified** helper/gates in that L09 measurement pass: focused
`tests/lexical_extraction/test_acceptance.py` **6 passed**; combined
`tests/lexical_extraction/` **196 passed**; `scripts/quality.ps1` passed — Ruff
check, Ruff format check (89 files already formatted), Pyright 0 errors /
0 warnings / 0 informations, pytest **466 passed**.

---

## 1r. Prior current state — 2026-09-28 L08 final spool correction

**Implemented** correction in `src/app/lexical_extraction/dictionary_aggregation.py`
and focused tests only. L01–L07 behavior is unchanged. Prior L08 ordering/bounds/
completion correction remains in force. L07 remains **user-accepted**. Corrected
L08 remains **implemented** and **test-verified**. Per L09 authorization,
L01–L08 are treated as the accepted baseline for the L09 measurement above.
Fuzzy matching, value parsing, unit aggregation, runner/CLI, monitoring,
review-UI projection, and publication remain **unimplemented**.

- Final spool `commit()` failures translate to bounded
  `DictionaryAggregationError(SPOOL_WRITE_FAILED)` with rollback; they do not
  escape as raw `sqlite3.Error` or claim completed coverage. Upstream L07 /
  lookup / field-mapping failures keep their own codes.
- Per-block capacity uses a disk-backed `block_hit_counts` primary-key counter in
  the same temporary spool (upserted with each discovery insert in the deferred
  transaction). Capacity no longer issues per-hit `COUNT(*)` against
  `discoveries`. `_load_block_hits` still uses `LIMIT result_buffer_records + 1`.
  Insert and counter stay aligned via rollback on error.

**Test-verified** in this L08 final spool correction: `scripts/quality.ps1`
passed — Ruff check, Ruff format check (87 files already formatted), Pyright
0 errors / 0 warnings / 0 informations, pytest **460 passed**. Focused
`tests/lexical_extraction/test_dictionary_aggregation.py` **20 passed**. Combined
`tests/lexical_extraction/` **190 passed**.

**Early full-Materials feasibility check:** completed in current §1 (L09).

**Not done:** fuzzy matching, value parsing, unit/`UnitOccurrence` aggregation,
component orchestration, runner/CLI, monitoring, publication.

---

## 1q. Prior current state — 2026-09-28 L08 ordering/bounds/completion correction

**Implemented** correction in `src/app/lexical_extraction/dictionary_aggregation.py`
and focused tests only. L01–L07 behavior is unchanged. The optional L01
`supporting_row_ids` field is unchanged. L07 remains **user-accepted**. Corrected
L08 remained **implemented** and **test-verified**, and was **not user-accepted**;
commit-error translation and disk-backed block counters were corrected in the
following pass (prior §1r / current §1).

---

## 1p. Prior current state — 2026-09-28 L08 bounded dictionary aggregation

**Implemented** in `src/app/lexical_extraction/dictionary_aggregation.py`, with the
minimal additive L01 field `supporting_row_ids` on the shared candidate base in
`contracts.py`. L01–L07 behavior is otherwise unchanged. L07 (including the
projection/search-error correction) is **user-accepted**. L08 was **implemented**
and **test-verified**, and is **not user-accepted**; ordering, bounds, unmatched
spool completion, and cleanup were corrected in the following pass (current §1).

---

## 1o. Prior current state — 2026-09-28 L07 projection/search-error correction

**Implemented** correction in `src/app/lexical_extraction/dictionary_matcher.py`
only. L01–L06 behavior is unchanged. L06 remains **user-accepted**. L07 matching
core remains **implemented** and **test-verified** after this correction, and was
subsequently **user-accepted** as the L07 baseline before L08 (see current §1).

- `_project_discovery` skips only L06 `BOUNDARY_REJECTED` and
  `PARTIAL_NORMALIZATION_UNIT` as normal non-hits (for example substring `s`
  inside the `ß` → `ss` expansion). Other `ComparisonError` codes, including
  `INVALID_COMPARISON_RANGE`, `OFFSET_MISMATCH`, `BLOCK_SLICE_MISMATCH`, and
  `SURFACE_BLOCK_MISMATCH`, raise `DictionaryMatchError(PROJECTION_FAILED)` so
  broken coherence is not reported as successful coverage.
- Exceptions while creating **or consuming** the Aho–Corasick hit iterator are
  `MATCH_FAILED` with a bounded message. Block-source failures stay
  `BLOCK_READ_FAILED`. `GeneratorExit` is not treated as a match failure. Shard
  cleanup and replay-identity pinning are unchanged.

**Test-verified** in this L07 correction: `scripts/quality.ps1` passed — Ruff
check, Ruff format check (85 files already formatted), Pyright 0 errors /
0 warnings / 0 informations, pytest **439 passed**. Focused
`tests/lexical_extraction/test_dictionary_matcher.py` **11 passed**. Combined
`tests/lexical_extraction/` **169 passed**. Coverage includes the `ß`/`s`/`ss`
regression, injected `PROJECTION_FAILED` / `MATCH_FAILED`, ordinary boundary
skip, and release-on-failure.

**Not done:** occurrence/candidate aggregation, fuzzy matching, value parsing,
component orchestration, runner/CLI, monitoring, publication. Manual
pharmaceutical extraction acceptance is not applicable.

**Next safe step:** user review of corrected L07. Do not implement L08 from this
pass. Unrelated pending work remains the reviewed-HTML provenance browser check
and the Findings default manual verify below.

---

## 1n. Prior current state — 2026-09-28 L07 bounded Aho–Corasick raw discoveries

**Implemented** in `src/app/lexical_extraction/dictionary_matcher.py`. L01–L06
behavior is unchanged. L06 (including the compound-unit / hyphen boundary
correction) is **user-accepted**. Fuzzy matching, value parsing,
occurrence/candidate aggregation, runner/CLI, monitoring, and publication remain
**unimplemented**. L07 was **not user-accepted**; projection/search-error
boundary was corrected in the following pass (current §1).

- `iter_raw_discoveries(terms, blocks, limits)` streams intermediate `RawDiscovery`
  records (exact / normalized-exact) with original `CharSpan` values. It is not an
  L01 `DictionaryOccurrence`, candidate, or execution claim.
- Terms are sharded by L02 `max_terms_per_shard` (source references) and
  `max_term_codepoints_per_shard` (literal + comparison key + retained reference
  strings). Each shard builds real `pyahocorasick` automata partitioned by L06
  whitespace-collapse behavior, rescans every block, then releases automata and
  shard-local maps before the next shard. `result_buffer_records` bounds emission
  buffering only.
- Block input is a replayable `BlockReplaySource`: `StaticBlockSource` for synthetic
  fixtures, or `ReviewedHtmlBlockReplay` which reopens L03 HTML per pass and pins
  the finalized `html_sha256`. Changed or incomplete replay identity fails closed
  (`REPLAY_IDENTITY_CHANGED` / `REPLAY_INCOMPLETE`). One-shot readers are not
  silently exhausted.
- Hits preserve all source references sharing a comparison key, repeated
  occurrences, overlaps, and original dictionary spellings. Exact requires
  `span.matched_text ==` the L05 literal; otherwise normalized-exact. L06 projection
  and per-reference boundaries apply. `fuzzy_enabled` is ignored.
- Oversized single references, shard construction failures, and block-read failures
  raise bounded `DictionaryMatchError` and do not report successful complete
  coverage. Early generator close releases shard state.

**Test-verified** in the initial L07 pass: `scripts/quality.ps1` passed — Ruff
check, Ruff format check (85 files already formatted), Pyright 0 errors /
0 warnings / 0 informations, pytest **435 passed**. Focused
`tests/lexical_extraction/test_dictionary_matcher.py` **7 passed**. Combined
`tests/lexical_extraction/` **165 passed**. Tiny fixtures use an independent
exhaustive reference; shard multisets remain invariant under count and
code-point limits.

**Optional reviewed-HTML smoke:** not performed in that pass. Not presented as
full-Materials time/peak-memory measurement.

**Not done at that date:** occurrence/candidate aggregation, fuzzy matching, value
parsing, component orchestration, runner/CLI, monitoring, publication.

**Next safe step at that date:** user review of L07. Projection/search-error
correction followed before acceptance.

---

## 1m. Prior current state — 2026-09-28 L06 boundary correction (compound units / hyphen)

**Implemented** correction in `src/app/lexical_extraction/comparison.py` only.
L01–L05 behavior is unchanged. L05 remains **user-accepted**. L06 helpers were
**implemented** in that pass and are now **user-accepted** as the L06 baseline
before L07 (see current §1). Matching beyond L07, fuzzy, value parsing,
aggregation, runner/CLI, monitoring, and publication remain **unimplemented**.

- `atomic_unit` continuation now includes `/`, middle dot `·`, hyphen-minus,
  superscript signs (`⁻`/`⁺` and related), and numeric characters in categories
  `Nd` and `No`, plus letters/marks/connectors. Shorter hits inside `min⁻¹`,
  `mL·min⁻¹`, `kg²`, and `rpm/min` are rejected. Complete compounds such as
  `min⁻¹` and `mL/min` still project. Left number-adjacent permission is ordinary
  decimal `Nd` only (`37°C`, `120rpm`); superscript `No` is not a fresh numeric
  boundary.
- `default` treats an adjacent hyphen-minus as word/code continuation, so
  `glucose` in `glucose-6-phosphate` and `water` in `water-soluble` are rejected,
  while a full punctuation-bearing chemical term and space-separated phrase
  overlaps (`granulation` / `wet granulation`) remain valid.
- V1 composition scope is documented accurately: NFC of each
  starter+combining-mark unit, then `casefold` — not a whole-string NFC pass
  (adjacent Hangul Jamo stay uncomposed). Comparison text, offset projection,
  complete-unit alignment, and `ComparisonError` behavior are otherwise unchanged.

**Test-verified** in this L06 boundary correction: `scripts/quality.ps1` passed —
Ruff check, Ruff format check (83 files already formatted), Pyright 0 errors /
0 warnings / 0 informations, pytest **428 passed**. Focused
`tests/lexical_extraction/test_comparison.py` **22 passed**. Combined
`tests/lexical_extraction/` **158 passed**.

**Not done at that date:** Aho–Corasick / document matching, fuzzy matching, value
parsing, occurrence aggregation, component orchestration, runner/CLI, monitoring,
publication. Manual pharmaceutical extraction acceptance is not applicable.

**Next safe step at that date:** user review of corrected L06. The user
subsequently accepted L06 (including this boundary correction). Unrelated pending
work remains the reviewed-HTML provenance browser check and the Findings default
manual verify below.

---

## 1l. Prior current state — 2026-09-28 L06 fixed V1 comparison normalization and boundaries

**Implemented** in `src/app/lexical_extraction/comparison.py`. Pure helpers
normalize one L05 term or one L03 block into temporary comparison text, map
comparison ranges back to original Unicode code-point offsets, and apply
role-aware boundary checks. L01–L05 behavior is unchanged. L05 is
**user-accepted**. Document matching, Aho–Corasick, fuzzy distance, value
parsing, occurrence aggregation, runner/CLI, monitoring, and publication remain
**unimplemented**. L06 is **not user-accepted**. Boundary false positives for
shorter units inside compounds and hyphen-connected materials were corrected in
the following pass (current §1).

- `normalize_term` / `normalize_block` / `normalize_literal` build an immutable
  `ComparisonSurface` (comparison text + per-unit original provenance). L03/L05
  source objects are not mutated. No global term list, normalized snapshot, or
  persistent index.
- Fixed V1 rules by L05 role/hint: per-unit NFC + `casefold`; natural-language
  roles also collapse whitespace runs (including CR/LF) to one separator;
  materials, UNII (`whole_code`), and units (`atomic_unit`) do not collapse
  whitespace and do not strip chemical punctuation, signs, digits,
  stereochemistry, unit slashes, or superscripts. No stemming, NFKC, accent
  stripping, OCR hyphen repair, or lookalike transliteration.
- `project_comparison_range` / `project_against_block` require complete
  normalization units, return an L01 `CharSpan` with
  `original[start:end] == matched_text`, and reject mid-expansion / off-by-one
  projections. Empty or whitespace-only term keys and malformed ranges raise
  bounded `ComparisonError`.
- Boundaries check original exteriors (pre-correction wording retained here for
  history; see current §1 for the corrected compound-unit and hyphen rules).

**Test-verified** in the initial L06 pass: `scripts/quality.ps1` passed — Ruff
check, Ruff format check (83 files already formatted), Pyright 0 errors /
0 warnings / 0 informations, pytest **423 passed**. Focused
`tests/lexical_extraction/test_comparison.py` **17 passed**. Combined
`tests/lexical_extraction/` **153 passed**.

**Optional reviewed-HTML single-block probe:** not performed. No reviewed HTML v1
sample with `data-review-html-version` was present in this workspace (local
`out/comparison/fexofenadine-local-current/document.html` is unreviewed
conversion HTML). This pass did not measure full-Materials matching or memory.

**Not done at that date:** Aho–Corasick / document matching, fuzzy matching, value
parsing, occurrence aggregation, component orchestration, runner/CLI, monitoring,
publication.

**Next safe step at that date:** user review of L06. Boundary correction followed
before acceptance.

---

## 1k. Prior current state — 2026-09-28 L05 fixed V1 source-field mapping (user-accepted)

**Implemented** in `src/app/lexical_extraction/field_mapping.py`. Maps L04 flat
`SourceRow` cells to compact, source-backed eligible search-term records for
independently selected lexical components. L01–L04 behavior is unchanged. L04 is
**user-accepted**. Normalization (now L06), document matching, Aho–Corasick, fuzzy
distance, value parsing, occurrence aggregation, runner/CLI, monitoring, and
publication remain **unimplemented** relative to that pass. **User-accepted** as
the L05 baseline before L06.

- `map_source_row(row, components=..., snapshot_id=...)` is a pure per-row mapper
  over the shared L04 `SourceRow`. It emits zero or more `EligibleSearchTerm`
  records. It does not build L01 candidates or `DictionaryOccurrence`.
- `iter_eligible_terms` streams terms from an already validated L04 handle and
  scans only tables required by the selected components. No global vocabulary or
  persistent index is built. Distinct source rows and same-spelling references
  stay separate.
- Fixed V1 field boundaries: FDA/EMA `material_name` / `alias_name` / `UNII`
  (whole-code, no fuzzy); ChEBI `material_name` / `alias_name` only; Equipment
  `Equipment type (EN)` / `Operating parameter (EN)` / eligible atomic `Unit`;
  Unit Operations `Search term (EN)` only when `Index this row` is exact `TRUE`,
  and independently eligible `Process step (EN)`. Excluded: CAS, SMS_ID/CHEBI_ID
  search, Greek columns, brand/model/range, UO purpose/relationship/A-B/inference.
- Compact terms carry original literal spelling, component/term role, source
  table/field/`row_id`, optional `lexical_term_id` / snapshot id, selected native
  IDs/display/qualification/traceability, and fixed internal boundary/fuzzy hints.
  Blank optional IDs stay absent; usable naming rows are kept.
- Exact case-insensitive unavailable markers (`N/A`, `NA`, `unknown`, `None`) are
  excluded from UNII **code search** and from optional native ID attributes. They
  are not applied to Materials names/aliases. L04 source cells stay unchanged;
  naming rows remain when the native ID is unavailable.
- Equipment `Unit` uses a fixed conservative atomic-token rule (placeholders,
  alternatives, footnote `¹`, dash/semicolon prose, whitespace, pure numerics, and
  ranges are ineligible; `min⁻¹` and slash compounds without spaces remain
  eligible). Catalogue context does not fill document values.
- UO `Match policy` / `record_type` distinctions are preserved for the five known
  policies and two known record types. Support, inspection, and step-cue policies
  map to `generic_cue` and do not attach an invented `Operation ID`. Unrecognized
  nonempty policy/record-type values on an otherwise active UO search row raise
  `FieldMappingError` instead of inventing a direct candidate. Diagnostic messages
  keep stable error codes and stay ≤200 characters by truncating only the embedded
  `row_id` context; source `row_id` values are not limited or mutated. Unknown
  `Index this row` values do not authorize. `Index this row=FALSE` does not
  suppress an independently eligible process-step term.
- `fuzzy_allowed` is an internal hint only: natural-language roles with a single
  alphabetic word of length ≥6 may be true; chemicals/UNII/units, phrases, short
  words, and context/support/inspection/generic-cue policies stay false. No fuzzy
  distance is calculated in L05.

**Test-verified** in this L05 error-bounds correction: `scripts/quality.ps1` passed —
Ruff check, Ruff format check (81 files already formatted), Pyright 0 errors /
0 warnings / 0 informations, pytest **406 passed**. Focused
`tests/lexical_extraction/test_field_mapping.py` **39 passed**. Combined
`tests/lexical_extraction/` **136 passed**.

**Bounded production mapping smoke (prior eligibility correction):** snapshot
`flat-v1-a39c0b393ffdbd4e97ed`. Representative first-row mapping still produces the
expected roles. First 5,000 FDA/EMA `UNII` cells: **0** exact unavailable markers
(`N/A`/`NA`/`unknown`/`None`). First-row equipment/UO fuzzy hints were false for
multiword phrases as expected. This error-bounds pass did not rerun that smoke.
This is not pharmaceutical content acceptance and not human acceptance of the
mapper.

**Not done:** dictionary normalization, document matching, fuzzy matching, value
parsing, occurrence aggregation, component orchestration, runner/CLI, monitoring,
publication. Full Materials time/peak-memory measurement remains deferred until
after matching and aggregation. Manual pharmaceutical extraction acceptance is
not applicable.

**Next safe step at that date:** user review of corrected L05. The user
subsequently accepted L05. Unrelated pending work remains the reviewed-HTML
provenance browser check and the Findings default manual verify below.

---

## 1j. Prior current state — 2026-09-28 L04 read-only flat SQLite snapshot access (user-accepted)

**Implemented** in `src/app/lexical_extraction/knowledge_snapshot.py`. One preflight of an
existing flat snapshot returns a pinned read-only handle and an L01
`KnowledgeSnapshotIdentity`. L01/L02/L03 behavior is unchanged. Fixed field mapping was
unimplemented at the end of that pass and is now L05. Normalization, matching, fuzzy,
values, aggregation, runner/CLI, monitoring, and publication remain **unimplemented**.
**User-accepted** as the L04 baseline before L05.

- `open_knowledge_snapshot(snapshot_directory, read_batch_rows, cache_kib)` and
  `open_knowledge_snapshot_from_configuration` validate once. Success yields
  `KnowledgeSnapshot`. Direct construction is not open. `close` and the context manager
  release the single connection. Reads before a successful open and after close raise
  `SNAPSHOT_NOT_OPEN`.
- Companions required: `knowledge.sqlite`, `manifest.json`, `validation_report.json`, and a
  nonempty snapshot `FLAT_SQLITE_CONTRACT.md`. The stored contract text and producer hash
  are not compared with the repository. Manifest `completion_status` must be the string
  `complete`. Schema and database `user_version` must be the exact JSON integer `1`
  (Booleans, floats, and numeric strings are rejected). Preparation version
  `flat-sqlite-1`, database file name, size, and streamed SHA-256 must agree. Report
  integrity, content-digest, source-preservation, and WAL-absence evidence must be strict
  JSON types, and table names, headers, column counts, and imported row counts must match
  the manifest and the fixed v1 headers. CSV paths named in the manifest are not opened.
  No repair, import, or preparation.
- `snapshot_id` must equal the producer derivation from the validated
  `snapshot_identity`: `flat-v1-` plus the first 20 lowercase hex characters of SHA-256
  over UTF-8 `json.dumps(..., sort_keys=True, separators=(",", ":"))`. Identity sources
  must list the four expected names and hashes in producer order; a reordered list is
  rejected and does not keep the original ID. The filesystem directory name need not equal
  `snapshot_id`.
- The database opens through a `file:` URI with `mode=ro`, then `PRAGMA query_only=ON`,
  with the L02 cache size and an in-memory temp store. Preflight requires journal mode
  `delete`, user version 1, `PRAGMA integrity_check` `ok`, exactly the four rowid tables,
  `TEXT NOT NULL` columns, `row_id` as the only primary key, and `COUNT(*)` equal to the
  manifest. A WAL header or `-wal`/`-shm`/`-journal` sidecar is `WAL_PRESENT`.
- `read_batch` / `iter_batches` page one allowlisted table with
  `rowid > after_rowid ORDER BY rowid LIMIT batch_size`, starting at zero, including the
  empty final page. The batch cannot exceed the validated limit. `lookup` uses that table's
  source `row_id` and returns the row or `None`. `scan_cursor` is this file's SQLite
  `rowid`. Cells stay stored strings. No joins, extra indexes, or field interpretation.
- Identity: `snapshot_id`, `database_sha256`, `manifest_sha256` of the exact manifest bytes,
  `schema_user_version` 1, `preparation_version` `flat-sqlite-1`. The database hash is
  streamed in finite chunks. After preflight, database changes are detected by size and
  modification time; the three small companions are re-hashed before each read. A detectable
  change is `SNAPSHOT_CHANGED`, the connection closes, and the previous identity is not
  applied to the new bytes. `SnapshotReadError.to_structured_error()` maps to
  `SafeStructuredError`.

**Test-verified** in the L04 provenance correction: `scripts/quality.ps1` passed — Ruff
check, Ruff format check (79 files already formatted), Pyright 0 errors / 0 warnings /
0 informations, pytest **367 passed**. Focused
`tests/lexical_extraction/test_knowledge_snapshot.py` **40 passed** (Boolean schema/user
version rejections, mismatched `snapshot_id`, reordered identity sources, producer-derived
fixture IDs, and a production-manifest derivation check without opening the large database).
Combined `tests/lexical_extraction/` **97 passed**.

**Read-only production smoke check (L04 correction session):** snapshot
`C:\Users\User\Desktop\MBR_core\RAG-Core-data\Agregate-Items\Prepared\flat-sqlite\flat-v1-a39c0b393ffdbd4e97ed`.
Preflight 7.681 seconds. Two pages of five rows and one `row_id` lookup per table, 0.019
seconds. Identity `snapshot_id` `flat-v1-a39c0b393ffdbd4e97ed`, preparation `flat-sqlite-1`,
user version 1, database SHA-256
`cd709652a4b4de5acf9ca8558a2423fb3e8ebf83e0fde5994cca47af922468f2` (matches the recorded
build), manifest SHA-256 `c312cf8c455b0bcb816db906f7faaa3258dd9f28f9650ba12fa146049e390937`.
Database size 441,327,616 bytes. Companion hashes unchanged. No WAL, SHM, or journal sidecar
before or after. This is not pharmaceutical content acceptance and not human acceptance of
the snapshot.

**Not done at that date:** fixed per-table search-field mapping, dictionary normalization,
matching, fuzzy matching, value parsing, component orchestration, runner/CLI, monitoring,
publication. Field mapping was implemented later as L05.

**Next safe step at that date:** user review of the corrected L04. The user subsequently
accepted L04. Unrelated pending work remains the reviewed-HTML provenance browser check and
the Findings default manual verify below.

---

## 1i. Prior current state — 2026-09-28 L03 reviewed HTML v1 reader (user-accepted)

**Implemented** in `src/app/lexical_extraction/html_reader.py` (bounded streaming correction).
Reads reviewed HTML v1 into L01 `PageRecord` / `BlockEvidence` with empty occurrences.
L01/L02 and the reviewed HTML producer are unchanged. Matching, normalization, fuzzy,
values, aggregation, runner/CLI, monitoring, and publication were **unimplemented** at the
end of that pass. **User-accepted** as the L03 baseline before L04.

- Production path: `iter_pages()` streams the file in finite byte chunks with incremental
  UTF-8 decoding and hashes the exact bytes parsed. Completed pages are emitted and released;
  the whole HTML text and a growing list of all pages are not retained. Retained state is the
  current page/block, a short completed-page queue, the decode/feed chunk, and duplicate
  identity sets for page numbers and node IDs (grow with distinct IDs, not file size alone).
  `read_all_pages()` remains a small/test convenience only.
- Root version must be the exact string `"1"` (`"01"`, `"+1"`, whitespace variants rejected).
  Duplicate provenance attributes fail closed (`DUPLICATE_HTML_ATTRIBUTE`).
- Root attributes are checked when `<html>` is seen. Final `ReviewedHtmlV1Input` (including
  whole-file SHA-256) is available only after successful full iteration when `completed` is
  True. Early stop or late error ⇒ `completed` False and no finalized validated-input digest.
- Fail closed when source-bearing `p`/`h2`/`h3`/`h4`/`footer`/`td`/`th` inside
  `article.element` lack `data-node-id`, appear outside `article.element` on a page,
  when bare non-whitespace text sits directly in an article, when an unsupported/void tag
  carries `data-node-id`, when `data-table-id` ≠ owning `data-element-id`, or when
  unexpected nested markup appears inside a source block.
- Skip `data-generated="true"` subtrees and head/style/script/nav. Kind mapping unchanged.
  `data-source-id` space-split limitation unchanged.
- No PDF/JSON/SQLite reads; no file creation; renderer unchanged.

**Test-verified** in this L03 final structural correction: `scripts/quality.ps1` passed —
Ruff check, Ruff format check (77 files already formatted), Pyright 0 errors / 0 warnings /
0 informations, pytest **327 passed**. Focused
`tests/lexical_extraction/test_html_reader.py` **19 passed**. Combined
`tests/lexical_extraction/` **57 passed**.

**Reviewed HTML sample smoke check:** no newly exported reviewed HTML v1 sample was available
in this Cursor workspace. An independent prior scratch run reported 18 pages / 728 blocks and
SHA-256 `e38333226b2beb96a01a4566233064a2e399beabb6e92bd63eeca25f46e2f7d5`; that is not
re-executed here. Historical conversion `document.html` was not substituted. Smoke check in
this session: **unverified** (sample absent).

**Not done at that date:** snapshot access, catalogue field mapping, matching/normalization,
fuzzy, values, aggregation, runner/CLI, monitoring, publication. Manual pharmaceutical
extraction acceptance is not applicable. Snapshot access was implemented later as L04.

**Next safe step at that date:** user review of the corrected L03 reader. The user
subsequently accepted L03. Unrelated pending work remains the reviewed-HTML provenance
browser check and the Findings default manual verify below.

---

## 1h. Prior current state — 2026-09-28 L02 execution configuration (user-accepted)

**Implemented** in `src/app/lexical_extraction/configuration.py`. Strict YAML loading,
fixed preset→component resolution, finite resource safeguards, and effective-configuration
SHA-256. L01 contracts in `contracts.py` are unchanged. The lexical engine is **not
implemented** beyond configuration and (now) HTML reading.

- Root schema version is strict integer `1`. Required mappings: `input`, `knowledge`,
  `output`, `extraction`, `resources`. Unknown keys are rejected at every level.
- Relative paths resolve against the configuration file's parent directory, never the
  process CWD. Resolved absolute `Path` values are returned. Paths are not required to
  exist and are not created by the loader.
- Presets and components use the locked L01 vocabularies. At least one preset or component
  is required. Duplicates within each requested list are invalid. Overlap between a preset
  and an independently requested component is valid. Resolved components are the
  deterministic union in canonical order. Requested list order is preserved separately and
  does not change the operational digest.
- `fuzzy_enabled` is the only matching switch; it defaults to `false` when omitted. No
  policy, algorithm, field-selector, or LLM settings are accepted.
- Resource defaults (safeguards only): `sqlite_read_batch_rows` 5000 (max 100000),
  `sqlite_cache_kib` 65536 (max 1048576), `max_terms_per_shard` 2000000 (max 10000000),
  `max_term_codepoints_per_shard` 50000000 (max 500000000), `result_buffer_records` 50000
  (max 1000000). Strict positive integers; string/bool coercion is rejected.
- Typed `SelectionOverride` may replace YAML `presets`, `components`, and/or
  `fuzzy_enabled` entirely before resolution; lists never append implicitly.
- Effective digest is lower-case SHA-256 of UTF-8 canonical JSON (`sort_keys=True`, compact
  separators, `ensure_ascii=False`, `allow_nan=False`), with sorted request sets. Suitable
  for `RunProvenance.configuration_sha256`.
- Synthetic example: `examples/lexical_extraction/execution-config.example.yaml`.

**Test-verified** in the L02 pass: `scripts/quality.ps1` passed — Ruff check, Ruff format
check (75 files already formatted), Pyright 0 errors / 0 warnings / 0 informations,
pytest **308 passed**. Focused `tests/lexical_extraction/test_configuration.py` **19 passed**
(parametrized preset coverage included). Combined `tests/lexical_extraction/` **38 passed**.

**User-accepted** as the L02 baseline before L03.

---

## 1g. Prior current state — 2026-09-25 L01 lexical contracts

**Implemented** in `src/app/lexical_extraction/contracts.py` only. These are typed evidence,
candidate, unit/value, provenance, extraction-outcome, and publication-claim records.
The lexical engine is **not implemented**. Parsing, search, real-data performance, monitoring,
and artifact publication are **unimplemented** and **unverified**.

- Reviewed HTML v1 input requires the HTML SHA-256, contract version 1, and producer root
  metadata (`job_id`, `review_revision_id`, `review_generation`, `conversion_status`). An
  external document id may be absent. A pre-validation failure has no validated-input record.
- Character spans are zero-based half-open Unicode code points. Slice equality is checked only
  with the block. Empty block text and missing OCR references are valid.
- A dictionary occurrence needs at least one source-backed candidate. Exact evidence must
  repeat the span text. Normalized-exact and fuzzy claims are stored, not computed. Fuzzy
  evidence is one alphabetic word of at least six characters and a recorded edit distance of
  at most one. Chemicals, UNII, and units cannot be fuzzy. No confidence score is stored.
- Value `raw_expression`, unit spelling, and nested spans must agree. A unit mention checks
  its own literal against its span. Value occurrences carry fixed rule `lexical-v1-value`.
- Run provenance stores requested presets separately from requested and resolved components.
  `rules_sha256` is a supplied digest. Resolved components must each have one executed outcome.
- Extraction outcomes are `not_requested`, `completed` (including a measured zero), `partial`,
  and `failed`. Publication is separate: a final manifest claim is valid only with completed
  publication. The contract does not prove files were written.
- Preset expansion is not implemented in L01; L02 owns fixed preset resolution.
- Synthetic example: `examples/lexical_extraction/result-example.json`. It is not a real extraction.

Material alias text is stored as supplied. FDA/EMA and ChEBI column rules do not filter aliases
by language. Equipment and Unit Operations dedicated-Greek-field exclusions are unchanged.

**Test-verified** in the L01 documentation correction: `scripts/quality.ps1` passed — Ruff check,
Ruff format check (73 files already formatted), Pyright 0 errors / 0 warnings / 0 informations,
pytest **289 passed**. Focused `tests/lexical_extraction/test_contracts.py` is included (19 tests).
Pyright printed no missing-file notices.

**Not done at that date:** HTML reading, snapshot queries, normalization, matching, value parsing,
fuzzy distance, aggregation, run control, monitoring, and publication. L01 was later user-accepted
as the baseline for L02.

---

## 1f. Prior current state — 2026-09-25 Flat knowledge SQLite

**Implemented** as a standalone preparation utility. The earlier normalized design
(`terms`, `lexical_entries`, `entry_sources`, `source_records`) was not built and is
superseded. There is one flat table per source CSV. The lexical extraction engine is
**not implemented**.

- `scripts/prepare_lexical_knowledge_sqlite.py` streams the four current final CSVs into
  `knowledge.sqlite` (`PRAGMA user_version` 1, preparation `flat-sqlite-1`). Every source
  column is `TEXT NOT NULL`. `row_id` is the primary key. Empty cells stay empty strings.
  Fully blank records are counted and skipped; this snapshot skipped none. No foreign keys,
  extra columns, or second search index.
- Consumer contract: `docs/FLAT_SQLITE_CONTRACT.md`, copied into a snapshot at publication.
  The already published snapshot keeps the contract text it was built with.
- Pytest can import the script because `pyproject.toml` sets `pythonpath = ["scripts"]`.
- CSV reading uses the standard parser with `strict=True`. An unterminated quote is
  `MALFORMED_RECORD`. An oversized field remains `FIELD_TOO_LARGE`.
- Reuse requires `knowledge.sqlite`, `manifest.json`, `validation_report.json`, and a
  nonempty `FLAT_SQLITE_CONTRACT.md`, plus report evidence that matches the manifest
  table counts. An incomplete snapshot is left in place; a new run writes a separate
  directory. Reuse does not compare the stored contract or producer hash with later code.

**Test-verified** in this correction pass: `scripts/quality.ps1` passed — Ruff check, Ruff
format check (69 files already formatted), Pyright 0 errors / 0 warnings / 0 informations,
pytest **270 passed**. Focused `tests/test_prepare_lexical_knowledge_sqlite.py` is included
(10 tests). A read-only smoke test of the published snapshot opened `mode=ro` with
`PRAGMA query_only=ON`, read two batches of five rows from each table, and matched each
chosen `row_id` lookup to that scan row. Database hash and companion hashes were unchanged
and no WAL sidecar appeared. Pyright also printed pre-existing missing-file notices for scripts later removed from the
repository; those notices did not fail the gate. The production build below
was not rerun. Human acceptance of the snapshot remains pending.

Published snapshot (sources unchanged; content digests match; `PRAGMA integrity_check` ok;
no WAL sidecar):

`C:\Users\User\Desktop\MBR_core\RAG-Core-data\Agregate-Items\Prepared\flat-sqlite\flat-v1-a39c0b393ffdbd4e97ed`

| Table | Rows | Columns | Source bytes |
|---|---:|---:|---:|
| `materials_fda_ema` | 1,111,030 | 12 | 186,152,422 |
| `materials_chebi` | 604,363 | 13 | 166,345,767 |
| `equipment` | 415 | 14 | 186,240 |
| `unit_operations` | 2,597 | 37 | 2,324,980 |

Database size 441,327,616 bytes. SHA-256
`cd709652a4b4de5acf9ca8558a2423fb3e8ebf83e0fde5994cca47af922468f2`.
Build elapsed 71.2 seconds inside the publisher. Batch size 5,000. Cache 65,536 KiB.
Journal `DELETE`, synchronous `FULL`. Peak working set 112,705,536 bytes by Windows
`GetProcessMemoryInfo` (`windows_psapi_peak_working_set`).

Those row, column, and byte counts match the 2026-09-25 profile reference. The profile
JSON still names historical `*_enhanced.csv` paths; this build used the current filenames
in the flat-SQLite prompt, and those files have the profile's byte sizes. `row_id` lookup
uses each table's `sqlite_autoindex_*`.

The three previously discussed unit-operation wordings are still stored as
`direct_candidate` / `Index this row` `TRUE`, with scope
`Manufacturing process text; Category is not an exclusion filter`
(`cell culture expansion` UO-029, four rows; `liquid bottle filling` UO-072, three rows;
`controlled rate freezing` UO-098, four rows). They were not edited.

**Not done:** lexical search, document matching, and human acceptance of this snapshot.
Import success is not pharmaceutical correctness.

**Next safe step:** review the snapshot contract, manifest, and validation report. Do not
implement the lexical engine from this preparation. Unrelated pending work remains the
reviewed-HTML provenance browser check and the Findings default manual verify below.

---

## 1e. Prior current state — 2026-09-25 Reviewed HTML provenance attributes

**Implemented** in `src/app/document_review/rendering.py` only. Newly rendered reviewed HTML
carries non-visible attribute contract version 1 so a later lexical reader can locate evidence.
The lexical engine itself is **not implemented**.

- Root `<html>`: `data-review-html-version="1"`, `data-job-id`, `data-review-revision-id`,
  `data-review-generation`, `data-conversion-status` from the supplied revision.
- Catalogue identities, resolved by physical page and structural path: `data-element-id` on
  each `article.element`, `data-node-id` on rendered element text, titles, cells, and footers,
  and `data-table-id` on each `<table>` (the owning element node).
- `data-source-id` is that node's own ordered, de-duplicated OCR block IDs. Empty reference
  lists omit the attribute. A missing or ambiguous catalogue node raises `ReviewError`
  `INVALID_REVIEW_STATE` (HTTP 409 if it surfaces through approval). `approve` renders before
  `put_export` and `_persist`, so a render failure does not publish a head.
- `data-generated="true"` marks the summary header, the partial-conversion banner, and each
  `Page N` heading. Source headings and footers are unmarked.
- Visible text is the current revision text. Previously approved export bytes are not rewritten.

**Test-verified** in this pass: `scripts/quality.ps1` passed — Ruff check, Ruff format check
(67 files already formatted), Pyright 0 errors / 0 warnings / 0 informations, pytest **260 passed**.
Focused `tests/document_review/test_rendering.py` plus `tests/document_review/test_backend_review.py`
were green before the full gate (24 tests). Pyright also printed pre-existing missing-file notices for scripts later removed from the
repository; those notices did not fail the gate. Manual browser acceptance of the
new attributes is **unverified**.

**Not done:** lexical extraction, highlighting, search JavaScript, review JSON schema changes,
mapping/ID changes, and any rewrite of historical exports. HTML metadata is not proof of
authenticity or regulatory compliance. Source references identify original OCR blocks; displayed
text may include reviewed corrections.

**Client fix (2026-09-25, implemented):** `approvePage()` and `approveDocument()` clear
`state.error` only after a response passes `isReviewState`, is not stale or a generation
conflict, and `prepareProjection` / `applyPrepared` succeed. A prior `REVIEW_NOT_READY` banner
no longer remains after a later successful Approve & Export. Conflicts, malformed responses,
projection failures, and pending/blocked states still keep their errors. Backend and HTML
provenance attributes were not changed. Focused regression is in `frontend/tests/state.test.ts`.
Host `npm --prefix frontend run typecheck` failed: `vue-tsc` is a Unix shim, not a Windows
command. `node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` in `frontend/` exited 0 on Node
20.18.0. `vitest` then failed because `@rolldown/binding` is missing (this `node_modules` is
not a Windows install). Docker Desktop was started, but the daemon was still down after three
minutes, so the Node 22.12 container path was not run. The new test and `npm test` / `npm run
build` are **unverified** in this session.

**Next safe step:** user browser verification of the isolated harness checklist in §2, including
that a failed Approve & Export banner disappears after a later successful approval. Do not
reset protected review directories. Unrelated pending work remains the Findings default manual
verify and the Unit Operations production CSV authorization below.

---

## 1c. Prior current state — 2026-09-24 Flat Unit Operations CSV builder (utility only)

This is the cross-session restart anchor. Repository code and tests are the source of truth for
implementation. Existing local-harness evidence is the source of truth for manually verified
review behaviour. Do not treat planned work as implemented.

### Unit Operations flat consolidation (2026-09-24)

**Implemented** (code + synthetic tests only; production CSV run **not** authorized):

- `scripts/build_unified_unit_operations.py` — stdlib builder that joins
  `uo_unified_table.csv`, `uo_lexical_terms.csv`, and `uo_operation_links.csv` into one flat
  denormalized `Unified_Unit_Operations.csv` (**37** scalar columns). Row grain is one combination
  of main-table step row × assigned lexical row × incident link row; generic blank-ID step cues
  append separately. Stable entity IDs (`row_id`, `category_id`, `process_step_id`,
  `lexical_term_id`, `source_evidence_id`, `link_id`) are deterministic SHA-256 prefixes;
  construction ordinals are internal only and are not output columns. `Operation ID` remains the
  unit-operation identifier (no duplicate column). Defaults point at the Desktop Unit-Operations
  directory; CLI is `--input-dir` / `--output`.
- `tests/test_build_unified_unit_operations.py` — focused temporary-fixture coverage
  (multiplication, missing terms/links, generic cues, link directions, Unicode/multiline,
  conflict/output preservation, shared entity IDs, collision failure, CLI). **Test-verified** on
  synthetic inputs only (19 passed after the stable-ID supplement).

**Not done in this pass:** production consolidation against the Desktop source CSVs;
`Unified_Unit_Operations.csv` creation from those inputs; dictionary updates; lexical search;
RAG. Do not run the production command until the user explicitly authorizes it.

**Next safe step for this utility:** user review of the builder, then an explicit separate
authorization to run the production command. Unrelated product next step remains Findings
default manual verify / prior handoff items below.

---

## 1b. Prior current state — 2026-09-18 Findings filter default: This page

The sections below retain the previous conversion/review handoff. They were not re-executed in
the Unit Operations builder pass.

### Product

**BatchLens Extract** has two core product legs.

1. **Evidence-preserving document preparation and review — CURRENT / IMPLEMENTED in this
   repository; not production-qualified.** Flow:

   ```text
   source PDF
     → Textract raw result (textract.json)
     → Textractor/conversion
     → canonical document.json + unreviewed HTML
     → human review / revisions / approvals
     → reviewed HTML/JSON exports
   ```

   The review workspace supports text-only corrections. Document structure, table identities,
   geometry, and protected source relationships must remain protected. Current document-review
   approval is not batch release, regulatory release, or a 21 CFR Part 11 electronic signature.

2. **Pharmaceutical information extraction — APPROVED TARGET / not implemented.** Extract
   pharmaceutical facts, recipe/process data, and other structured information from the reviewed
   document, preserving evidence and provenance links to the source document and reviewed
   revision.

A later rules capability may evaluate extracted facts against versioned FDA, EU, or customer
rules. That layer is **not implemented** and must not drive premature architecture. **BatchLens
Audit** remains a separate planned tool ([00](00_project_reference.md),
[08](08_check_selection_strategy.md)).

### Implementation status

**Implemented** (code present in the working tree; conversion and review are feature-flagged and
disabled by default in `create_app`):

- FastAPI foundation: `/health`, `/ready`, `/version`
- Conversion: AWS Textract SDK boundary, Amazon Textractor 1.10.0, durable DynamoDB/S3/SQS job
  FSM, Cognito-owned upload/jobs shell, canonical `document.json` + unreviewed HTML
- Review: Vue 3, TipTap 3, PDF.js workspace; backend under `src/app/document_review/`; review API
  routes; revision, decision, approval, validation, mapping, and export logic; intended
  production composition using Cognito `sub`, DynamoDB review heads/conditional writes, and
  versioned S3 review artifacts
- Local review harness under `tests/document_review/`
- A1 Save operation identity is the agreed working baseline. HTTP `PUT /review` still returns
  top-level `ReviewState`. Optional request `operation_id`; committed `save_operation` metadata
  on new `DRAFT_SAVED` envelopes (`schema_version` 1.1.0); server fingerprint v1; committed-chain
  replay; explicit `TextChange.origin` / `finding_id` for new changes; internal
  `update_with_receipt` and `reconcile_save_operation`. Legacy omitted/null operation IDs keep
  existing conflict behaviour and do not receive fabricated operation metadata. Isolated
  local HTTP Save/retry verification is recorded below.
- A2 browser Save identity/recovery (implemented; safety-corrected then F1–F3 follow-up
  2026-09-18; **manually accepted** in the preceding session against the isolated 8766
  checklist: ordinary Save/reload, real post-commit lost-response recovery, reload recovery,
  page-approval invalidation, tolerance suggestions, and same-directory harness restart).
  The original A2 contracts remain. Additional safety in force in the browser: exclusive
  action reservation before the first await; outcomes bound to captured workspace generation,
  context, and operation; current-key corrupt/actor-mismatch records are preserved and block
  mutation rather than being overwritten; runtime validation of pending records, ReviewContext,
  OperationLookup, and consumed ReviewState fields, including coherent lookup head/receipt
  relationships; known-commit versus pre-dispatch versus uncertain network outcomes;
  matching-record cleanup only; attempted-work presentation of text changes and finding
  decisions; revalidated context after terminal lookup/state GET before apply, disposition, or
  cleanup; in-session uncertainty preserved when metadata writes fail; recovered records
  are not treated as first-attempt-safe for a later 422. Recovery remains sessionStorage,
  same-tab, storage available. Automatic retirement remains only after exact guarded PUT
  confirmation, safe state application, and successful matching cleanup, or after explicit
  disposition with terminal proof. No operation TTL or multi-tab coordination. The local
  harness writes a derived `history.jsonl` after successful publication; A2 does not use
  it for Save reconciliation.
- B1 committed-history projector (2026-09-18 C2 frozen-head integrity; **user-accepted**
  after a separate isolated local-review regression: Save/reload, approval invalidation,
  suggestions, final export). Pure fail-closed in-memory projection of one frozen
  published `ReviewHead` parent chain (`src/app/document_review/history.py`,
  `project_committed_history`). Derived output only; it does not publish heads, mutate
  revisions, or verify source/raw/export bytes. Coverage states completeness through the
  supplied head revision/generation. Causal order is generation plus validated parent
  links; `revision_created_at` is envelope `created_at` (server revision creation before
  conditional head publication), not the publication instant. The frozen head's status,
  document approval, and export pointers must equal the top revision it points to; a
  mismatched supplied head is `INVALID_REVIEW_STATE`. Unpublished CAS candidates are
  excluded. Legacy missing `origin` remains `UNKNOWN`. Copied-forward finding
  decisions/approvals are not re-emitted. A derived `DERIVED_OUTCOME` invalidation is
  emitted only when a prior page/document approval is **absent** in the next snapshot; a
  repeated Approve page / Approve & Export grant is a later grant, not an invalidation.
  `DOCUMENT_APPROVED` without that revision's approval and stored HTML/JSON export
  pointers is `INVALID_REVIEW_STATE`. Present approvals whose content/document hashes do
  not match the current snapshot fail closed. Not a second record store and not a
  wire/API feature.
- B2a atomic `history.jsonl` materialisation (2026-09-18 C1 I/O normalisation;
  **accepted** as the test-verified derived-file primitive): `src/app/document_review/history_jsonl.py`
  writes one UTF-8 JSONL file from a successful B1 projection. The first line is
  `HISTORY_COVERAGE` (schema `batchlens.committed-history.jsonl.v1`) embedding B1 coverage
  through the named revision/generation; following lines are chronological
  `COMMITTED_TRANSITION` records. Same-directory exclusive temp, fsync, then replace.
  Any failure to prepare or write the final target path is
  `HistoryJsonlError(code="HISTORY_JSONL_WRITE_FAILED")`, never a raw `OSError`, and does
  not report coverage. A previous valid final file is left untouched. After a successful
  replace, leftover-temp cleanup is best-effort. Status is `CURRENT` / `STALE` /
  `INVALID_OR_MISSING`. Not an authority and not used for Save reconciliation.
- B2b local published-history rebuild (2026-09-18; **proposed-and-testable locally**;
  test-only harness/adapter): after `LocalReviewStore.publish` atomically publishes a
  `ReviewHead`, the adapter rebuilds `data-dir/history.jsonl` from that head via B2a.
  Startup inspects B2a status and rebuilds when `INVALID_OR_MISSING` or `STALE`; a
  `CURRENT` file is not rewritten merely because the harness restarted. No published
  head means no fake empty history file. A failed conditional publish does not
  materialise. Rebuild happens after the authoritative head write, so failure cannot
  roll back the committed revision; the caller receives
  `LOCAL_HISTORY_REBUILD_FAILED` (HTTP 503 on the local harness) rather than a normal
  Save/approval `ReviewState`. One structured operational log event records only safe
  correlation fields (event, job id, revision id, generation, history path, trigger
  `publish`/`startup`, error code/type). Supported model: one local harness process per
  `--data-dir`. The in-process `RLock` is not a directory lock and does not provide
  multi-process writer safety. Not wired into production cloud persistence, HTTP history
  routes, or the browser.
- HITL editor-boundary corrections (2026-09-16; still in the working tree): protected table
  `sourcePath` / `rows` / `columns`; page `setContent` failure reporting; single-application
  tolerance replacement handling; heading mapping for canonical `title` / `section_heading`;
  stable table-cell `data-source-cell` identity and node-decoration highlighting
- Later UI work present in code and frontend tests (not claimed as visual browser verification
  unless listed under manually verified): Vite `process.env.NODE_ENV` browser-bundle define;
  document status label; `Document findings` / `Page findings` counts; short accessible
  decision-button help text; immediate pending/recorded finding-decision feedback;
  Findings scope default **This page** (2026-09-18; `scope` ref initialises to `'page'`;
  an explicit **All warnings** choice is preserved across page navigation; empty pages
  keep `No findings in this view.` and do not fall back to document-wide findings)

**Test-verified** (latest executed gates: 2026-09-18 Findings filter default This page):

- Frontend (this Findings-default pass), `node:22.12-bookworm-slim` review-builder
  `batchlens-review-builder:findings-scope`: `npm --prefix frontend run typecheck` passed;
  focused `npm --prefix frontend test -- tests/findings-panel.test.ts` **15 passed**;
  complete `npm --prefix frontend test` with host `out/` mounted **100 passed**
  (12 files). First complete-suite run without `out/` failed `sample-roundtrip.test.ts`
  (`ENOENT` for the excluded comparison sample); that failure is not a product defect.
  `docker build --target review-builder` emitted `review.js`, `review.css`, and the
  PDF worker; assets copied into `src/app/document_review/static/`. Docker Python
  image, host npm, harness restart, OCR, and full-repo pytest were not run in this pass.
- Historical 2026-09-18 B2b local published-history rebuild: focused B1+B2a+local-history
  **51 passed**; `poetry run pytest tests/document_review/` **104 passed**; ruff/pyright
  clean. Those totals are not this Findings-default run.
- Historical 2026-09-18 B2a-C1 I/O normalisation: focused history tests **36 passed**;
  `poetry run pytest tests/document_review/` **95 passed**; ruff/pyright clean. That total
  is not this B2b run.
- Historical 2026-09-18 B2a JSONL materialisation: focused history tests **34 passed**;
  `poetry run pytest tests/document_review/` **93 passed**; ruff/pyright clean. That total
  is not this C1 run.
- Historical 2026-09-18 B1-C2 frozen-head integrity: focused history tests **19 passed**;
  `poetry run pytest tests/document_review/` **78 passed**; ruff/pyright clean. That total
  is not this B2a run.
- Historical 2026-09-18 B1-C1 correction: focused history tests **16 passed**;
  `poetry run pytest tests/document_review/` **75 passed**; ruff/pyright clean. That total
  is not this C2 run.
- Historical 2026-09-18 B1 projector implementation: focused history tests **10 passed**;
  `poetry run pytest tests/document_review/` **69 passed**; ruff/pyright clean. That total
  is not this C2 run.
- Historical 2026-09-18 A2 F1–F3 follow-up: `poetry run ruff check src tests` passed;
  `poetry run ruff format --check src tests` passed (59 files already formatted);
  `poetry run pyright` 0 errors/0 warnings/0 informations; `poetry run pytest` **206 passed**.
  Frontend in `node:22.12-bookworm-slim` with the existing lockfile: `npm run typecheck`
  passed; `npm test` **94 passed**; `npm run build` emitted `review.js`, `review.css`, and a
  local PDF.js worker into `src/app/document_review/static/`. Those totals are not this B1 run.
- Historical 2026-09-18 A2 pending-Save safety correction: Python **206 passed**;
  frontend **84 passed**. Those totals are not this follow-up's run.
- Historical 2026-09-17 A2 implementation pass: Python **206 passed**; frontend **57 passed**.
  Those totals are not this follow-up's run.
- Historical 2026-09-17 A1 acceptance-closure pass: Ruff passed, 58 files formatted, Pyright
  0/0, 199 Python tests passed; focused A1 `test_save_operations.py` plus
  `test_backend_review.py` 42 passed. That total is not this A2 run.
- Historical 2026-09-17 A1 implementation pass: Ruff passed, 58 files formatted, Pyright 0/0,
  189 Python tests passed; focused A1 32 passed. That total is not this run.
- Historical 2026-09-16 HITL correction pass: Ruff passed, 57 files formatted, Pyright 0/0, 152
  Python tests passed. 148 is historical from the HITL implementation session; 134 remains
  historical conversion evidence. Those totals are not this session's run.
- Frontend in `node:22.12-bookworm-slim` (historical 2026-09-16): typecheck passed, 23 tests
  passed (was 11 before that correction pass). That total is not this A2 run.
- Real `document.json` from `out/comparison/fexofenadine-textractor-20260916-173938/` loaded
  through the production TipTap extension list: all 18 pages passed projection → editor →
  structural validation with no sparse text changes. Sequential page loads including 18 → 1
  showed only that page's source IDs. The sample was not committed. That check is not browser
  acceptance.

**Manually verified locally** (user, local harness, localhost only; supplied originals
untouched):

- Side-by-side source PDF and editable converted document
- Synchronized page navigation, pagination, and PDF zoom
- Text editing
- Save draft with successful `PUT .../review`
- Persistence after browser reload, hard reload, and harness restart
- Findings filters
- Pending and recorded finding-decision feedback
- Page approval
- Approval invalidation after edit and save
- Final export rejection while unresolved or unapproved work remained
- Successful final reviewed HTML and JSON downloads after completion
- A deliberate test edit remaining in both reviewed exports

**User-accepted** (preceding session, 2026-09-18, isolated 8766 A2 checklist; not re-executed
in this B1 pass):

- Ordinary Save draft then F5 retained the text and left editing available
- Real post-commit lost-response recovery via Check save status
- Reload recovery with an outstanding pending record
- Page-approval invalidation after a subsequent saved edit
- Page-5 tolerance suggestions when applicable
- Same-directory harness restart retained existing semantics

**User-accepted** (2026-09-18, isolated local-review B1 regression; not re-executed in this
B2b pass): Save/reload, approval invalidation, suggestions, and final export. B1 is locked
except for a defect discovered directly in a later authorised task.

**User-reported** (2026-09-17, completed review on
`.local-review-data/fexofenadine-local-current`; not independently re-executed here; not
A1 human acceptance):

- Both page-5 tolerance suggestions were applied and saved
- Both corrections survived browser reload
- Page approval and Approve and export succeeded
- Both corrections appeared in the downloaded HTML and JSON
- After harness restart, the corrections, Approved state, and export downloads remained
  available

**Not deployed / not integration-verified:**

- Real Cognito authorization
- DynamoDB conditional writes against AWS
- S3 versioning
- AWS/IAM deployment or CloudFormation apply
- Production qualification
- 21 CFR Part 11 or other regulatory compliance
- Visual browser verification of the latest cosmetic UI (status label, findings counts,
  decision-button help text)

**Future / not implemented:**

- Pharmaceutical extraction (leg 2)
- Recipe graph visualization
- Rules / Audit evaluation
- Deliverable B2c/later production history publication, operator UI, retry policy,
  centralized operational logging, concurrent writers/process crashes, backup/restore,
  referenced artifact byte checks, retention/access control (B2b is local single-process
  harness wiring only)
- Persistent audit/observability ledger (direction recorded below; A1 reuses the committed
  revision chain and does not add a ledger)
- Multi-tab coordinated editing, recovery after tab close/storage clearing/private-mode
  restrictions, and independently writable clones of one store (A2 same-tab sessionStorage
  only)

### Local harness purpose and boundaries

`tests.document_review.local_harness` is development/test-only. It reuses the actual review
service, API routes, validation, mapping, frontend bundle, and export logic. It substitutes only
external identity and storage. It uses synthetic reviewer `local-test-reviewer` and synthetic
completed job `local-fexofenadine`, binds to `127.0.0.1`, persists generated review state under
`.local-review-data/` (gitignored), and leaves the supplied original PDF, `document.json`,
`textract.json`, and `document.html` untouched.

It does not verify real Cognito authorization, DynamoDB conditional writes, S3 versioning, or AWS
deployment. jsdom/component tests and API tests are not browser acceptance.

### Future audit/provenance direction (B1 accepted; B2a primitive; B2b local wiring)

A1 **implemented** committed-revision Save reconciliation. It is not a complete audit trail.
A2 implements same-tab browser recovery; it is not a complete audit trail. B1 **implemented**
and **user-accepted** a derived in-memory committed-history projection of the published
parent chain. B2a **implemented** and **accepted** as the atomic `history.jsonl` primitive
with embedded coverage and `CURRENT` / `STALE` / `INVALID_OR_MISSING` status. B2b
**implemented** local-harness rebuild after successful `LocalReviewStore.publish` and on
startup when the derived file is missing/invalid/stale. The file remains a replaceable
derived view. `head.json` plus reachable immutable revision envelopes remain
authoritative. A committed Save/approval is distinct from a post-publish history rebuild
failure: the revision stays committed; B2b surfaces `LOCAL_HISTORY_REBUILD_FAILED` and
does not mint another revision. One local harness process per `--data-dir` is supported;
multi-process writers, process-crash recovery of a partial rebuild, and backup/restore
are **not** guaranteed. B2c/later may decide production routing, operator UI, retry
policy, and centralized operational logging. Referenced artifact byte checks, retention,
access control, and privileged filesystem modification remain outside this guarantee.

Historical recorded direction (superseded as an authoritative store, retained as context): an
independent append-only JSON Lines ledger such as `.audit/audit-events.jsonl`.
The current engineering direction is to treat published revisions as authoritative evidence
and project a readable history file from that chain. B1 is the projector; B2a is the file
primitive; B2b is local-harness rebuild of that file after published heads.

- The ledger, if added later, must remain outside source control and Docker images.
- Operational logs remain structured stdout logs, not another persistent audit file.
- Future audit events should store references, IDs, hashes, revision links, actors, times,
  actions, and outcomes — not duplicate full PDFs or complete JSON artifacts.
- A hash chain can be tamper-evident, but is not proof of tamper-proof storage or Part 11
  compliance.
- Operation-aware search uses the retained committed chain with no separate operation TTL.
  Deleting retained revisions ends the supported lookup guarantee. A1 tests use one process
  and shared in-memory doubles; they do not prove multiprocess file safety or live DynamoDB/S3.

### Key non-goals for current work

- Batch release, regulatory release, or Part 11 electronic signature claims
- Recipe extraction, graph visualization, collaboration, or an extra identity/database service
- Implementing B2c production history routing, operator UI, extraction, rules, or cloud
  deployment in this B2b pass; do not start B2c from this local wiring alone
- Reopening accepted Textractor conversion behaviour
- Treating UI regression or automated tests as human acceptance of A1

The earlier HITL implementation (backend, local harness, IAM template, Docker) remains in the
working tree. No AWS calls, commit, push, deployment, CloudFormation, OCR, or infrastructure
change in this documentation pass.

## 2. Local review command

Build with Node 22.12+ and start from the repository root. Paths are relative to the repository
root. `--data-dir` defaults to `.local-review-data/fexofenadine`. Use a different data directory
when inputs change; a changed input is rejected instead of resetting existing review history.
Personal acceptance may use a distinct directory such as
`.local-review-data/fexofenadine-manual-01`. Do not use
`.local-review-data/fexofenadine-correction-verification/` for personal acceptance.

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
poetry run python -m tests.document_review.local_harness --source "manual-input/source.pdf" --document "out/comparison/fexofenadine-textractor-20260916-173938/document.json" --textract "out/comparison/fexofenadine-textractor-20260916-173938/textract.json" --html "out/comparison/fexofenadine-textractor-20260916-173938/document.html" --data-dir ".local-review-data/fexofenadine" --port 8765
```

Open `http://127.0.0.1:8765/documents/local-review`. Supplied originals stay untouched. Saved
drafts/approvals/exports survive restarting with the same data directory; unsaved browser edits do
not survive browser closure.

This checkout already contains generated `src/app/document_review/static/` assets (`review.js`,
`review.css`, PDF worker), so the Python harness can start without rebuilding the frontend.
The user's completed current local review is `.local-review-data/fexofenadine-local-current`
(inputs `out/comparison/fexofenadine-local-current/document.json` and `document.html`, raw
OCR `out/comparison/fexofenadine-textractor-20260916-173938/textract.json`). Do not reset it.
Historical personal progress `.local-review-data/fexofenadine-manual-01` remains on disk; do
not reset it either. A1 isolated evidence
`.local-review-data/a1-save-retry-verification-20260917-192410` remains on disk; do not
reset it. B1 regression `.local-review-data/b1-regression-20260918` remains on disk; do
not reset it. Use a separate empty data directory for synthetic checks.

**Reviewed HTML provenance harness** (2026-09-25; started in this session; manual checklist
**unverified**). Fresh data directory and unused port 8769. Do not use 8765–8768 or any existing
review data directory. GET `http://127.0.0.1:8769/documents/local-review` returned HTTP 200
`Cache-Control: no-store`. GET review for `local-fexofenadine` returned `NOT_REVIEWED`,
generation 0. That is not browser acceptance. Originals were not modified.

```powershell
poetry run python -m tests.document_review.local_harness --source "manual-input/source.pdf" --document "out/comparison/fexofenadine-local-current/document.json" --textract "out/comparison/fexofenadine-textractor-20260916-173938/textract.json" --html "out/comparison/fexofenadine-local-current/document.html" --data-dir ".local-review-data/html-provenance-20260925" --port 8769
```

Open `http://127.0.0.1:8769/documents/local-review`. Job `local-fexofenadine`, bearer
`local-review-token`. Manual checklist (user browser; not done in this session):

1. Open the isolated workspace and confirm page navigation, text, and tables display normally.
2. Edit text, Save draft, reload, and confirm persistence.
3. Approve a page, edit/save again, and confirm its approval is invalidated.
4. Confirm Approve & Export still blocks incomplete review. Complete the required review and download newly approved HTML and JSON.
5. Open the HTML: visible content and tables remain correct. Inspect source for revision metadata, representative paragraph/cell IDs, source references where available, and generated-content markers.
6. Confirm both exports contain the saved correction, and restarting the same isolated harness preserves its saved state.

**B2b isolated harness** (2026-09-18; command for the user's manual run; **not executed
in this implementation session**). New `--data-dir` and unused port. Do not use 8765,
8766, or 8767.

```powershell
poetry run python -m tests.document_review.local_harness --source "manual-input/source.pdf" --document "out/comparison/fexofenadine-local-current/document.json" --textract "out/comparison/fexofenadine-textractor-20260916-173938/textract.json" --html "out/comparison/fexofenadine-local-current/document.html" --data-dir ".local-review-data/b2b-history-20260918" --port 8768
```

Open `http://127.0.0.1:8768/documents/local-review`. Job `local-fexofenadine`, bearer
`local-review-token`. Startup should print the resolved `history:` path. Manual steps:

1. Make at least one Save draft and confirm `.local-review-data/b2b-history-20260918/history.jsonl` appears.
2. Complete the existing page-5 two-suggestion / page-approval / Approve and export flow.
3. Stop and restart the same harness directory and port.
4. Inspect the first JSONL coverage line and confirm its revision/generation match `head.json`.
5. Note whether a missing/invalid file was rebuilt to current, or an explicit
   `LOCAL_HISTORY_REBUILD_FAILED` startup failure occurred.

**A2 isolated harness** (2026-09-18 F1–F3 follow-up restart; same directory as the
2026-09-17 startup and morning correction restart; user's 8765 process left running;
this restart itself was not the later A2 acceptance):

```powershell
poetry run python -m tests.document_review.local_harness --source "manual-input/source.pdf" --document "out/comparison/fexofenadine-local-current/document.json" --textract "out/comparison/fexofenadine-textractor-20260916-173938/textract.json" --html "out/comparison/fexofenadine-local-current/document.html" --data-dir ".local-review-data/a2-save-recovery-20260917" --port 8766
```

Open `http://127.0.0.1:8766/documents/local-review`. Job `local-fexofenadine`, bearer
`local-review-token`. Reused `review-context.json` storage ID
`08c3e9b4-3b70-42ee-81a2-8bde3ae9fb64` (not regenerated). No review head was written.
Live GET checks on this restarted process: `/documents/local-review` HTTP 200
`Cache-Control: no-store`; `GET /api/v1/documents/jobs/local-fexofenadine/review/context`
HTTP 200 `context_id=6bdec862ee21fd500e00b4cb2a8e1fab6299d4a622e49913fbd0da30fbee414e`,
`actor=local-test-reviewer`; GET review `NOT_REVIEWED` generation 0 `revision_id` null
with two page-5 `POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY` findings
(`finding_c084cac7554719ec066283115a746dcb`, `finding_dda8b3733bfb23d27ea12c08fc280cbd`).
This F1–F3 restart reconfirmed those same read-only GET values; no review head exists yet.
The 2026-09-17 lookup-without-header 422 and never-committed UUID `UNRESOLVED` checks
were not repeated as writes; they remain historical for that first startup.

Browser Save/reload/lost-response/approval/export and same-directory restart were
**accepted** in the preceding session against the isolated 8766 checklist. SessionStorage
recovery is same-tab only; tab close, storage clearing, and private-mode restrictions can
lose the pending record. After a successful Check/Retry confirmation and matching cleanup,
F5 must not leave the user blocked. A post-commit lost-response drill is not proof of
pre-commit in-flight absence.

Historical 2026-09-17 A1-closure harness startups (processes later stopped; not this
verification run): `--data-dir ".local-review-data/fexofenadine-manual-01" --port 8765`
(`IN_REVIEW`, generation 70, revision `7d1400d4-bc6c-44a0-be8a-cd7eeb5f2bbd`); isolated
`--data-dir ".local-review-data/a1-operation-api-check" --port 8766`. That isolated
directory was later removed as disposable runtime data.

**A1 local HTTP Save/retry verification** (2026-09-17 execution; isolated harness only;
user's 8765 review untouched; not human acceptance of A1):

```powershell
poetry run python -m tests.document_review.local_harness --source "manual-input/source.pdf" --document "out/comparison/fexofenadine-local-current/document.json" --textract "out/comparison/fexofenadine-textractor-20260916-173938/textract.json" --html "out/comparison/fexofenadine-local-current/document.html" --data-dir ".local-review-data/a1-save-retry-verification-20260917-192410" --port 8766
```

Evidence directory: `.local-review-data/a1-save-retry-verification-20260917-192410`.
Job `local-fexofenadine`, bearer `local-review-token`. Node
`node_36d6122f84e425aa74a50a8654f1d0b7` (page 1 `TABLE_CELL`, baseline `Item Type`)
chosen from that GET catalogue. Operations
`fa42fa71-da8a-4422-bf1e-3558921c4a19` (A) and `e475fa26-a162-4e99-a421-ca443438f0cf` (B).
PUT `/api/v1/documents/jobs/local-fexofenadine/review` returned top-level `ReviewState`
(no `receipt`). Save A → revision `4446700b-be5e-4d82-b6be-e01d829ac0fb` generation 1;
Save B → `d7a1ea21-c8e8-4874-bde8-8543404bbf1f` generation 2, text `A1-SAVE-B Item Type`.
Exact retry of A and a controlled stop/restart of this isolated process with the same
data directory both returned HTTP 200 with head B, generation 2, text B, and unchanged
revision-file hashes. Same operation A with different text returned HTTP 409
`SAVE_OPERATION_MISMATCH` with head/files unchanged. Committed envelope A records
operation A; envelope B records operation B and `parent_revision_id` A. Isolated process
stopped after the run. This is not browser recovery, power-loss durability, multiprocess
safety, or live-cloud verification.

`update(...)` still returns `ReviewState`. Receipts remain service-level; A2 adds HTTP
lookup of `reconcile_save_operation` without wrapping PUT. The A2 browser submits
`operation_id` and `X-Review-Context` for new Saves. UI tests are not browser acceptance.

## 3. Acceptance evidence and remaining unverified work

1. Local visual/functional acceptance against the source PDF: **COMPLETE** (user). Evidence is
   listed under §1 Manually verified locally. Do not extend that list to unlisted behaviour.
2. Historical 173938 conversion sample stored zero `POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY`
   warnings. The current local conversion (`out/comparison/fexofenadine-local-current`)
   produced two page-5 tolerance findings. **User-reported:** both suggestions were applied
   and saved on `.local-review-data/fexofenadine-local-current`. That report is not A1
   human acceptance.
3. Original orchestrator technical review of the working tree and gate evidence remains available
   as a later step; it is not local-harness acceptance.
4. Later production acceptance uses `/documents`, a Cognito-owned completed job, and a deployed
   version of the prepared IAM update. The local harness is not a cloud integration test.
5. A1 Save operation identity remains the agreed baseline. It is **test-verified** and has
   an isolated local HTTP Save/retry execution recorded in §2. It is **not human-accepted**.
   `svc.update(...)` still returns `ReviewState`.
6. A2 browser Save identity/recovery is **implemented**, **test-verified** (historical
   2026-09-18 F1–F3: Python 206, frontend 94, ruff/pyright, isolated 8766 GET checks), and
   **manually accepted** in the preceding session against the isolated 8766 checklist below.
   SessionStorage recovery remains same-tab only. A later 422 after an unknown outcome is not
   proof that an earlier request failed or was cancelled.
7. B1 committed-history projection is **implemented**, **test-verified**, and
   **user-accepted** after the isolated local-review regression. Causal order is generation
   plus parent links; `revision_created_at` is envelope creation time, not the CAS
   publication instant.
8. B2a `history.jsonl` materialisation is **implemented**, **test-verified**, and
   **accepted** as the derived-file primitive (historical C1: 36 focused B1+JSONL tests;
   95 document-review tests; ruff/pyright). Embedded coverage states exactly through
   which revision/generation the file is complete. Stale/invalid/missing is explicit.
   Path preparation and write failures are `HISTORY_JSONL_WRITE_FAILED`.
9. B2b local published-history rebuild is **implemented** and **test-verified**
   (historical this-session B2b: 51 focused tests; 104 document-review tests;
   ruff/pyright). It is local single-process harness wiring only. After a successful
   local publish, `data-dir/history.jsonl` is rebuilt from that head. Startup rebuilds
   missing/invalid/stale files and does not rewrite `CURRENT`. Post-publish rebuild
   failure leaves the committed head in place, preserves prior history bytes, logs a
   safe structured event, and returns `LOCAL_HISTORY_REBUILD_FAILED` rather than a
   normal Save/approval response. Referenced PDF/raw/export bytes are still not
   verified by the history file. Production cloud persistence, browser/UI, directory
   locking, and multi-process safety are **not implemented**.
10. Findings scope default **This page** is **implemented** and **test-verified** in this
    frontend pass (`FindingsPanel` `scope` ref `'page'`; focused 15; complete frontend
    100 with `out/` mounted; review-builder assets copied). It is **not manually
    accepted**. Counts remain findings counts, independent of the list filter. An
    explicit **All warnings** selection survives page navigation.

**Next safe step:** manually verify the Findings default on an existing local harness
after a hard reload of the rebuilt assets, without Save/approval. Do not stop the
running 8767/8768 processes. Do not start B2c or extraction.

### A2 manual checklist (accepted in the preceding session; isolated 8766 only)

1. Ordinary edit → **Save draft** → F5 retains the text and leaves editing available.
2. Lost response: make an unsaved edit, arm the one-shot fetch wrapper below, click
   **Save draft** once. The wrapper must await a real successful PUT before hiding it and
   must restore `fetch` automatically. Expected: unknown status, retained record, blocked
   new mutation. This post-commit drill does not prove pre-commit in-flight absence.
3. In that drill, click **Check save status**. A valid `COMMITTED` lookup plus exact
   replay/application/cleanup should retire the record and unlock editing. F5 after this
   successful recovery must not leave the user blocked.
4. To test reload with an outstanding record, use a separate edited Save/lost-response
   drill and press F5 **before** Check/Retry. The record must be read and reconciled. A
   committed operation may recover automatically through lookup and exact replay; a
   genuinely `UNRESOLVED` operation remains blocked without a new ID. Do not require it
   to remain blocked after successful confirmation.
5. **Approve page** / invalidation, both page-5 tolerance suggestions when still
   applicable, **Approve & Export**, and restart with the same isolated directory retain
   existing semantics. Do not reset progress merely to repeat a test.

Lost-response snippet (8766 only; one-shot; restores `fetch`):

```javascript
(() => {
  if (location.port !== '8766' || !location.pathname.startsWith('/documents/local-review')) {
    throw new Error('Run this only at http://127.0.0.1:8766/documents/local-review');
  }
  const original = window.fetch.bind(window);
  let used = false;
  window.fetch = async (input, init) => {
    const request = input instanceof Request ? input : new Request(input, init);
    const path = new URL(request.url, location.origin).pathname;
    const target = request.method === 'PUT' && path === '/api/v1/documents/jobs/local-fexofenadine/review';
    if (!target || used) return original(input, init);
    used = true;
    window.fetch = original;
    const response = await original(input, init);
    if (!response.ok) return response;
    await response.clone().arrayBuffer();
    throw new TypeError('A2 lost-response drill: server Save completed, browser hid the response.');
  };
  console.log('Armed: next review Save PUT completes on the server, then fails in the app.');
})();
```

---

## Historical HITL editor-boundary corrections — 2026-09-16

Four focused review-editor corrections were applied on top of the existing uncommitted HITL
slice. The accepted Textractor conversion was not reopened or changed. Local visual acceptance
was still pending at that date and is now recorded as complete in §1.

- Table `sourcePath` / `rows` / `columns` now survive the production TipTap schema, so
  projection, editor JSON, and structural validation agree. Page `setContent` is verified; a
  rejected load is reported and does not silently keep the previous page.
- Suggested ± replacements are queued for the guarded backend operation only. Identical preview
  text is omitted from sparse `changes`. Stale suggestions are refused; editing a preview
  invalidates the queued decision and keeps the newer text as a manual change.
- Canonical lowercase `title` and `section_heading` render as heading levels 2 and 3 in the
  editor and reviewed HTML. Table-title `TITLE` and ordinary text stay non-heading regions.
- Table cells/headers emit `data-source-cell` from the node attribute. Finding focus uses a
  node decoration so the existing highlight survives the table view.

At that date, `manual-input/source.pdf` had not yet been used for built-bundle browser
acceptance. jsdom/component tests and API tests were not browser acceptance.

## Historical conversion handoff — earlier 2026-09-16 correction pass

**Textractor integration complete with three focused corrections applied.**

Amazon Textractor 1.10.0 remains the active parser and HTML renderer.
All three corrections from the focused task are implemented, verified, and passing.

No commit, push, deployment, or live AWS call was performed.

## 2. What was integrated (original baseline)

Selected implementation: `C:\Users\User\Downloads\textractor_to_html.py`

The integration placed the PoC as `src/app/document_conversion/textractor_renderer.py`
and added a thin adapter in `src/app/document_conversion/adapter.py`.
See §3 for accepted PoC limitations that remain unchanged.

## 3. Three focused corrections (this session)

### 3.1 Partial-result visibility in full HTML

**Problem:** `render_full_document_html()` called `document_html(textractor_doc, raw_tables)`
without passing status or warnings.  PARTIAL_SUCCESS and AWS_PAGE_ERROR could appear in
`document.json` and `page-NNNN.html` but be absent from the downloadable `document.html`.

**Fix:**
- `document_html()` in `textractor_renderer.py` now accepts `status: str` and
  `warnings: Sequence[tuple[str, Sequence[int]]]` (defaults preserve existing callers).
- A `<div class="partial-banner">` is rendered between `<nav>` and `<details>` only for
  PARTIAL_SUCCESS; SUCCEEDED conversions get no banner.
- All warning codes and page references appear in the collapsed **Conversion notes**
  `<details>` section as an escaped `<ul>`.  Dynamic content (codes, page numbers) is
  HTML-escaped via `escaped()`.
- `render_full_document_html()` in `adapter.py` extracts `(w.code, list(w.pages))` pairs
  from the structured document and passes them to the renderer.
- Individual `page-NNNN.html` artifacts already received status/codes; unchanged.
- The POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY code receives a plain-language note in HTML:
  "Possible tolerance-symbol ambiguity. Check this value against the source PDF;
  the extracted text has not been changed."

### 3.2 Flexible table sizes (remove max_table_positions)

**Problem:** `ConversionLimits` contained `max_table_positions` (default 10 000).
`normalize.py` was deleted but the field remained; no code enforced it.
`max_relationship_depth` was also non-functional since normalize.py was removed.

**Changes:**
- `max_table_positions` removed from `ConversionLimits` (`contracts.py`).
  Passing it now raises a Pydantic `ValidationError` (extra="forbid").
- `max_relationship_depth` is now enforced via `_check_relationship_graph()` in
  `adapter.py`, called from `validate_textract_response()` before `textractor_parse()`.
- Algorithm: Kahn's topological sort (BFS).  Detects cycles (`CYCLIC_RELATIONSHIP`)
  and longest-path depth > max (`RELATIONSHIP_DEPTH_EXCEEDED`) in O(V+E).
- Overall block-count and page-count limits are preserved unchanged.
- Table size (row × column) is not limited; only relationship chain depth is checked.

### 3.3 Conservative tolerance-review detector

**Location:** `src/app/document_conversion/tolerance.py`

**Rules (all must hold):**
1. Explicit tolerance cue: `\btolerance\b` or `\ballowable\s+deviation\b` in same text.
2. Bare `+<number>` present (decimal separator: `.` or `,`; whitespace allowed).
3. Explicit `±` absent (already expressed).
4. Explicit asymmetric `+X / -Y` absent (already expressed).

**Not flagged:** plain addition, unit presence alone, "mass"/"weight"/"target".

**Output:** `Warning(code="POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY", pages=(page,), block_ids=(...))`

**Deduplication:** by frozenset of block_ids (source-region identity, not text identity).
Two items with identical text but different block_ids are treated as distinct source
locations and each produces its own warning.  Only an exact match of the block_id set
suppresses a duplicate.

**Guarantees:**
- `textract.json`, `document.json` text, `document.html` content: unchanged.
- No correction, annotation, or replacement inserted.
- SUCCEEDED status not changed to PARTIAL_SUCCESS for advisory findings alone.

## 4. Accepted PoC limitations (unchanged)

- Merged-cell reading order and within-cell line boundaries may be imperfect.
- Some table captions/headings appear twice (layout stream + direct table title).
- OCR symbols and undetected visual tables are not recovered.
- Checkbox-state detection: NOT_SELECTED displays as ☑ in HTML; document.json is correct.
- Caption markup may be duplicated in some documents.
- Adjacent tables with equal Textractor `reading_order` scores: insertion-order sort
  (PYTHONHASHSEED-dependent between runs; deterministic within a single run).

## 5. Offline regeneration command

```powershell
poetry run python -m app.document_conversion offline "out\comparison\fexofenadine-20260916-151835\textract.json" --source-id fexofenadine --output "out\comparison\fexofenadine-textractor-reviewed"
```

## 6. Real-sample verification — fexofenadine-textractor-reviewed

Input: `out\comparison\fexofenadine-20260916-151835\textract.json`
Output: `out\comparison\fexofenadine-textractor-reviewed\`

| Check | Result |
|---|---|
| 18 source pages | ✓ (18 `page-NNNN.html` artifacts; `id="source-page-18"` present) |
| 31 raw TABLE IDs represented exactly once | ✓ (31 `table-wrap` elements in `document.html`) |
| Page navigation controls present | ✓ |
| OCR text unchanged by detector | ✓ |
| PARTIAL_SUCCESS banner absent (status=SUCCEEDED) | ✓ |
| Warning list in Conversion notes | ✓ (19 UNINTERPRETED_LAYOUT_FIGURE warnings listed) |
| `document.json` validates against `contracts.Document` | ✓ |
| Existing output directories preserved | ✓ |

**Tolerance advisory findings in this sample:** None found.

The detector found zero expressions meeting its current same-element/cell rules.
Zero findings do not establish that tolerance transcription is correct in this sample.
Physical page 5 of the reviewed response contains separate LINE blocks for "If tolerance"
and "+0.1%"; the intended ± was NOT correctly recognized in that case.  The current
detector requires the cue word and ambiguous `+` to appear in the same extracted text
element or cell — detecting cues across different blocks or cells is outside this task's
scope and was not implemented.  Do not treat a clean advisory report as confirmation that
all tolerances are correctly transcribed; inspect the source PDF directly.

**Warnings breakdown:**
- 19 × UNINTERPRETED_LAYOUT_FIGURE (figure blocks skipped in HTML; block_id recorded)
- 0 × AWS warnings (clean SUCCEEDED response)
- 0 × POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY

## 7. Quality results (post-correction)

| Command | Result |
|---|---|
| `poetry run ruff check .` | Passed |
| `poetry run ruff format --check .` | Passed (43 files) |
| `poetry run pyright` | 0 errors, 0 warnings |
| `poetry run pytest` | **134 passed** |

Test count: 110 (baseline) → 132 (previous pass) → 134 (+2 new: large-table fixture, distinct-location deduplication).

## 8. Changed files (this session)

| File | Change |
|---|---|
| `src/app/document_conversion/contracts.py` | Removed `max_table_positions`; added docstring to `ConversionLimits` |
| `src/app/document_conversion/adapter.py` | Added `_check_relationship_graph()` (Kahn's BFS); call it in `validate_textract_response()`; import `Block`; import `detect_tolerance_ambiguities`; invoke detector in `convert_and_render()`; update `render_full_document_html()` to pass status/warnings |
| `src/app/document_conversion/textractor_renderer.py` | Updated `document_html()` signature (status, warnings); added `_warning_item_html()`; added partial banner and warning list HTML |
| `src/app/document_conversion/tolerance.py` | **NEW** — conservative tolerance-symbol ambiguity detector; deduplication by frozenset of block_ids (not text) |
| `tests/document_conversion/test_converter.py` | 22 focused tests (previous); +2 this pass: `_large_table_fixture` (101×100) + replaced `test_large_table_converts_without_truncation`; replaced `test_duplicate_text_on_same_page_produces_one_warning` with `test_same_source_region_deduplicated`; added `test_distinct_cells_same_text_retain_both_locations` and `test_same_text_different_pages_independently_reported` |

## 9. Preserved directories

| Directory | Status |
|---|---|
| `out\comparison\fexofenadine` | Unchanged |
| `out\comparison\fexofenadine-20260916-151835` | Unchanged (source input) |
| `out\comparison\fexofenadine-python-fixed` | Unchanged |
| `out\comparison\fexofenadine-textractor-standalone` | Unchanged |
| `out\comparison\fexofenadine-textractor-integrated` | Unchanged |
| `out\comparison\fexofenadine-textractor-reviewed` | NEW: reviewed output |

## 10. Historical next steps (superseded by current handoff above)

1. User/operator review of `out\comparison\fexofenadine-textractor-reviewed\document.html`.
2. Docker/API worker verification when requested.
3. Live AWS conversion was subsequently completed and accepted by the user.
4. No commit, push, or deployment without explicit instruction.

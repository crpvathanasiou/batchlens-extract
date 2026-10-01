# BatchLens — L07: Bounded exact and normalized Aho–Corasick discoveries

## Authorization and stop

L01–L06, including L06's compound-boundary correction, are **user-accepted**. Implement **L07 only**: a shared, transient Aho–Corasick dictionary matcher over the L05 eligible-term stream and L06 comparison surfaces. Emit source-backed **raw discoveries** with original document spans. Build bounded shards and release them after use. Do not start final occurrence/candidate aggregation, full-Materials measurement, fuzzy matching, value parsing, runner/CLI, monitoring, or publication. Stop for review before the next task.

This is not an end-to-end extractor or a user-facing search-algorithm choice. L02's only matching switch remains `fuzzy_enabled`, default false; L07 implements exact/normalized-exact regardless of that switch. Do not add algorithm, normalization, boundary, field, or policy configuration.

## Inspect the accepted baseline

In `C:\Users\User\batchlens-extract`, read `AGENTS.md`, current `.ai/03_common_handoff.md`, relevant `.ai/02_code_quality_standards.md`, `.ai/04_code_map.md`, `.ai/05_pipeline_contracts.md`, and the dictionary-matching sections of the lexical handoff if present. Inspect L01 `contracts.py`, L02 `configuration.py` resource limits, L03 `html_reader.py`, L04 `knowledge_snapshot.py`, L05 `field_mapping.py`, L06 `comparison.py`, and their focused tests. Use the current repository, not historical prompts, as the implementation baseline. The reported L06 gate was 22 focused, 158 lexical, and 428 total passing tests; produce this task's own evidence.

L05 supplies `EligibleSearchTerm` in bounded row-stream order, retaining distinct source rows and same-spelling alternatives. L06 supplies temporary normalized keys, per-block comparison-to-original offset maps, and fixed boundary checks. L01 `CharSpan` must equal the original `BlockEvidence.text` slice. The L06 composition scope is starter-plus-combining-mark units, as documented; do not silently replace its accepted behavior.

## Deliverable: one shared matching core

Create a focused module such as `src/app/lexical_extraction/dictionary_matcher.py`. Expose a narrow synchronous iterator/function accepting an iterable of L05 eligible terms, an iterable or repeatable bounded source of L03 blocks, and L02 `ResourceLimits` (or just the relevant finite limits). Design the block input deliberately: **each shard must see each eligible block**, without silently exhausting a one-shot reader or retaining the whole reviewed HTML in memory. A caller-provided reopening factory/replayable source, or a small explicitly bounded temporary spool, is acceptable; do not implement the production runner or publication. State its lifecycle and cleanup. For a real reviewed HTML replay, pin and compare L03's finalized validated input identity/hash across complete passes; changed or incomplete input must fail rather than mixing hits from different document bytes. Synthetic tests may use a small repeatable block source with an explicit stable identity.

For each shard:

1. Normalize eligible terms with L06. Partition by comparison behavior where needed (natural labels collapse whitespace; materials/codes/units do not), so every indexed key is searched against a block normalized by the **same** fixed behavior. Keep a multiword term whole.
2. Index distinct comparison keys with Aho–Corasick, retaining **all** compact source references and original term spellings sharing a key. No last-write-wins, arbitrary top candidate, term-language filter, or deduplication of separate source rows. Preserve role/boundary hint per reference even when normalized keys collide.
3. Apply L06 complete-unit projection and the **specific reference's** original-text boundary. Emit one raw discovery per eligible `(block, original span, source term reference)`; preserve repeated occurrences, overlaps, and ambiguous alternatives. Mark it `exact` only when the original block slice literally equals the L05 source term; otherwise mark it `normalized_exact`. Include the fixed L01 rule ID, component/role, source table/field/`row_id`, optional `lexical_term_id` and snapshot id, original dictionary term, block node id and `CharSpan`. This is an intermediate record, **not** an L01 `DictionaryOccurrence`, candidate, entity association, or execution claim.
4. Release the automaton and shard-local candidate map before constructing the next shard. Count **source term references**, not only distinct keys, against `max_terms_per_shard`; account for both raw and comparison term text plus retained reference strings under `max_term_codepoints_per_shard`. A single oversized term/reference, shard construction failure, or block-read failure must be explicit and must not appear as successful complete coverage. Do not silently truncate hits or discard a reference. Stream discoveries instead of accumulating a whole-run hit list; do not use an unbounded global key/reference/dedup set. Honor `result_buffer_records` if any buffering is used.

Shards may rescan blocks, as the accepted bounded-memory architecture states. The raw discovery **multiset** must be independent of shard limits for the same pinned inputs; raw emission order may reflect shard order. A later task will merge same-span discoveries, resolve full candidate metadata with indexed `row_id` lookup, impose canonical result order, and publish final L01 records. Do not claim those results are complete in L07. Include a clear match error/diagnostic boundary with safe bounded messages and appropriate cleanup on early close or failure. No database writes, persistent automaton, pickle cache, CSV import, or joins.

Use an actual multi-pattern Aho–Corasick implementation, not a per-term substring loop disguised as a shard. Inspect the current dependency/runtime support. If an additional package is justified, add it through Poetry and update both `pyproject.toml` and `poetry.lock`; avoid unrelated upgrades. A small in-project implementation is acceptable only if it remains understandable and the synthetic correctness/resource tests cover it. Do not add a configurable fallback algorithm.

## Meaningful tests

Add `tests/lexical_extraction/test_dictionary_matcher.py` using synthetic L05 terms and L03 blocks, with an **independent exhaustive reference** for tiny cases. Cover:

- Exact versus normalized-exact from real original slices (case change, decomposed accent, whitespace run), Unicode expansion alignment, page/block isolation, empty blocks, and source spelling retention.
- Repeated hits and valid overlapping phrases; shared normalized key with several FDA/EMA/ChEBI or equipment-scoped parameter references; same source row with distinct permitted fields; no merge of catalogue identities.
- Whole-code UNII (longer alphanumeric/hyphen/underscore rejected), the corrected compound-unit and hyphen boundaries, complete slash/reciprocal units, and number-adjacent units. No fuzzy, inferred relationships, or child-value requirement.
- Very small shard limits splitting same-key references across shards; compare discovery multisets and counts with a larger shard and the independent reference. Exercise both count and code-point limits, a single oversized item, block replay, changed replay identity, and early-stop/failure cleanup. Demonstrate the matcher does not retain an all-vocabulary or all-block collection. Avoid brittle timing-only assertions.

Run focused matcher tests, combined lexical tests, and `scripts/quality.ps1`; report the actual results. If a real reviewed HTML v1 export and snapshot are locally available, an **optional bounded read-only** smoke may use a small source subset. Do not present it as the agreed full-Materials time/peak-memory measurement: that follows matching **and aggregation**. State what was and was not verified.

## Files, DoD, completion report

Change only the new matcher module/tests, `pyproject.toml`/`poetry.lock` if needed for the Aho–Corasick dependency, and concise current-state entries in `.ai/03_common_handoff.md`, `.ai/04_code_map.md`, `.ai/05_pipeline_contracts.md`, `.ai/01_implementation_roadmap.md`. Record L06 as user-accepted. Preserve L01–L06, reviewed HTML producer, snapshot and existing application behavior. If a concrete accepted-interface incompatibility blocks this bounded implementation, report it rather than silently redesigning earlier modules.

Definition of Done: fixed-rule Aho–Corasick shards consume L05 terms, replay L03 blocks safely, and stream original-offset exact/normalized-exact discoveries with all source references; limits/failures are explicit, and tiny independent-reference tests verify overlap, ambiguity, and shard invariance. Return public signatures, shard/replay lifecycle, limits and failure behavior, changed files, test results, and remaining unimplemented work. **Stop after L07; await review and explicit acceptance before further work.**

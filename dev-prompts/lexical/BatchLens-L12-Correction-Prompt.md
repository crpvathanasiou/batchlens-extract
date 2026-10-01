# BatchLens — L12 focused correction: bounded counts and truthful sink lifecycle

## Baseline and scope

L01–L11 are user-accepted. L12 is implemented and test-verified but **awaiting user acceptance**. Correct only the L12 runner/sink issues below. Read `AGENTS.md`, current `.ai/03_common_handoff.md`, `src/app/lexical_extraction/{runner,monitoring,html_reader,field_mapping,parameter_unit_value}.py`, and `tests/lexical_extraction/test_runner.py`. Use the current repository versions. Preserve selected-component extraction, L01–L11 matching, L02 configuration, read-only snapshot behavior, and the current accepted unit rule (`normalized_exact` allowed, fuzzy forbidden).

## 1. Keep monitoring and page metadata bounded

`_CountingTermStream.row_keys` retains every distinct `(table, row_id)` across the run. A full Materials pass has millions of terms and many source rows; this set grows with the catalogue and defeats the bounded-memory runner. L05 yields terms row-by-row from a single-table paged scan, so count eligible rows with a running previous `(table, row_id)` key and an integer (or another demonstrably bounded method), without losing the distinction between rows and terms. Do not report all source rows as eligible when they emitted no terms.

`_validate_html` also retains `_PageMeta` for every page and `_emit_pages` reuses the whole list. Remove the all-pages retained list. Stream page evidence for each component from a fresh L03 reader (or an equivalent one-page-at-a-time replay) while preserving empty pages, document order, exact input identity checking, and the accepted block-stream behavior. A changed or incomplete page replay must fail the affected component, not publish completed coverage. Do not load the whole reviewed HTML into RAM.

## 2. Make sink ownership and finalization unambiguous

`EvidenceSink.write_page(page)` has no component argument. In a combined L10 run, multiple components are begun before interleaved block writes, so a later publisher cannot reliably assign each page skeleton to a component. Make the page-write boundary explicitly component-scoped (or use an equally explicit, testable per-component sink context); keep `write_block` consistent. Update the small test sink and protocol examples. Confirm each component receives its ordered pages, including empty pages, exactly once.

`_run_l10_group` completes components one at a time. If `complete_component` succeeds for component A but fails for B, the current catch block aborts and reports **all** components failed, including already completed A. Likewise, an exception from `sink.complete_run()` currently reaches the outer catch, which returns all components failed with `validated_input=None` and `knowledge=None` even after both were validated and some components completed. Keep already committed component outcomes and validated identities truthful. Abort only uncommitted/provisional components; expose the run-level sink-finalization failure explicitly (a small additive `LexicalRunResult` error/status field is acceptable). A secondary stream-close error must not erase the original component failure and prior completed outcomes. Never claim successful run publication or a final manifest after such failure. If a sink cannot safely preserve completed components after a run-level abort, document and test its required transaction behavior rather than returning contradictory success/failed states. Avoid adding a generic transaction framework.

## Focused regressions

- Feed many distinct eligible source rows through the counting path; verify accurate term/row counts with memory that does not grow as a set of row IDs. Include multiple terms per row and a row with no eligible term.
- Use a multi-page synthetic reviewed HTML with an empty page and combined L10 selection. Assert component-scoped page events, page order, complete replay identity, and no retained all-page list.
- Inject failure on the **second** `complete_component` in the L10 group. Verify the first committed component remains completed, the later component is failed/aborted, overall status is partial, and the sink is never told to abort a committed component.
- Inject `complete_run` failure after at least one component completed. Verify validated HTML/snapshot identities and committed component results are preserved, a structured run-level failure is visible, and no completed publication claim exists.
- Keep successful zero-result, isolated dictionary failure, failed HTML/snapshot preflight, fuzzy selection, units non-fuzzy, and stream cleanup behavior passing.

Run focused `tests/lexical_extraction/test_runner.py`, all `tests/lexical_extraction/`, and `scripts/quality.ps1`. Update `.ai/03_common_handoff.md` as the state anchor and concise `.ai/04_code_map.md` / `.ai/05_pipeline_contracts.md` descriptions if contracts change. Report changed files, public sink/result changes, actual checks, and remaining limits. L12 remains **awaiting user acceptance**. **Stop before L13; no CLI, final manifest, or review UI.**

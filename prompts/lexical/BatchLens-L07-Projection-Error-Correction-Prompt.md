# BatchLens — L07 focused projection and search-error correction

L01–L06 are user-accepted. L07 is implemented and test-verified according to the supplied report, but **not user-accepted**. Correct only the raw-hit projection/error boundary below in `src/app/lexical_extraction/dictionary_matcher.py`, its focused tests, and concise L07 state documentation. Do not begin L08, occurrence aggregation, fuzzy, values, runner, monitoring, publication, or full-Materials measurement.

## Independently reproduced issue

L06 maps the source character `ß` to the comparison string `ss` as one normalization unit. An eligible material alias `s` produces two Aho–Corasick substring hits inside that expanded unit. Each prospective hit should be skipped as a non-discovery because it splits the unit. Currently `_project_discovery` does **not** skip `PARTIAL_NORMALIZATION_UNIT`; it raises `DictionaryMatchError(PROJECTION_FAILED)` and aborts the shard. I reproduced this through `iter_raw_discoveries` using a tiny substitute automaton for the local probe because `pyahocorasick` is not installed in this review environment. The supplied Windows gate (7 focused, 165 lexical, 435 total tests) was not independently rerun here.

Conversely, `_project_discovery` currently skips `INVALID_COMPARISON_RANGE`, `OFFSET_MISMATCH`, `BLOCK_SLICE_MISMATCH`, and `SURFACE_BLOCK_MISMATCH`. These indicate an invalid AC range or broken internal surface/block coherence, not a normal lexical non-match; silently discarding the evidence would falsely suggest complete coverage. Only a failed word boundary or a valid AC substring lying *inside* one normalization unit is a normal non-hit.

There is one related diagnostic boundary: an exception raised **during iteration** of `automaton_iter(...)` is outside the existing `try` in `_match_block`, so `_stream_shard` labels it `BLOCK_READ_FAILED` even though block replay succeeded. It should be `MATCH_FAILED` with a safe bounded message.

## Required change and tests

- Skip only `BOUNDARY_REJECTED` and `PARTIAL_NORMALIZATION_UNIT` from L06 projection. Convert the other `ComparisonError` codes to explicit `DictionaryMatchError(PROJECTION_FAILED)`; preserve the original cause and do not emit a raw discovery for the bad range. Preserve L06's accepted source-offset behavior unchanged.
- Cover exceptions both when creating and when consuming the Aho–Corasick iterator as `MATCH_FAILED`. Do not hide block-source errors behind match errors, and do not catch `GeneratorExit` as a normal failure. Keep shard cleanup and replay identity semantics unchanged.
- Add a regression with term `s` and block `ß`: the matcher completes with zero discoveries. Include a simultaneous term `ss`, which must still yield one `normalized_exact` discovery with original span `[0,1)` and matched text `ß`. Compare the small result with the independent tiny reference, including a one-term-per-shard variant.
- Add focused injected-failure tests for a corrupted projection (`OFFSET_MISMATCH` or equivalent) raising `PROJECTION_FAILED` and an AC iterator failing after creation raising `MATCH_FAILED`; an ordinary boundary rejection remains a skipped hit. Assert the generator releases shard state on failure. Avoid a broad redesign or new error framework.

Change only `src/app/lexical_extraction/dictionary_matcher.py`, `tests/lexical_extraction/test_dictionary_matcher.py`, and minimal L07 facts in `.ai/03_common_handoff.md` / `.ai/05_pipeline_contracts.md` if needed. Keep the already accepted L01–L06 code, configuration, snapshot, and existing application behavior unchanged. Run focused matcher tests, combined lexical tests, and `scripts/quality.ps1`; report actual outcomes. Include `pyproject.toml` and `poetry.lock` or their dependency diff with the completion artifacts so the previously reported `pyahocorasick` addition can be reviewed without changing dependency scope in this pass.

Return changed files, precise skip-versus-failure rules, verification evidence and remaining limitations. **Stop with L07 awaiting explicit user acceptance; do not advance to L08.**

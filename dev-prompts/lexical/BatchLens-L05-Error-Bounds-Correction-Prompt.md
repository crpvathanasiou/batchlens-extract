# BatchLens L05 — bounded mapper error correction

Read the current `AGENTS.md`, `.ai/03_common_handoff.md`, and the L05 mapping code/tests. Work from the corrected L05 baseline only. L01–L04 are user-accepted; L05 is implemented and test-verified but awaits user acceptance. Do not start L06.

## Reproduced issue

`unit_operations.row_id` is a source `TEXT` key with no 200-character limit in the flat schema. On an active UO search row with an unrecognized `Match policy` or `record_type`, `_unit_operation_term_role` interpolates the full `row_id` into the diagnostic. A sufficiently long valid `row_id` makes `FieldMappingError.__init__` raise a plain `ValueError` because the diagnostic exceeds 200 characters. The explicit `UNKNOWN_MATCH_POLICY` or `UNKNOWN_RECORD_TYPE` error is lost. This was reproduced with a 200-character synthetic `row_id`; the reported Cursor quality gate and production snapshot checks were not independently rerun here.

## Required change

- Keep diagnostic messages bounded before constructing `FieldMappingError`, while preserving its stable error code and `SafeStructuredError` conversion. A short, safely truncated source-ID context is enough; do not impose a new limit on source `row_id` or mutate the L04 row. Apply the bound to `AMBIGUOUS_UO_CLASSIFICATION` as well.
- Keep all corrected L05 field eligibility, material aliases, unknown-policy handling, fuzzy hints, and process-step independence unchanged. No parser, matcher, value extraction, or L06 work.
- Add a focused regression for a long `row_id` with unknown policy and unknown record type. Assert each yields the intended `FieldMappingError` and bounded structured message. Cover the ambiguous classification path if it includes the row ID. Existing short-ID diagnostics should remain useful.

## Files and verification

Change only `src/app/lexical_extraction/field_mapping.py`, `tests/lexical_extraction/test_field_mapping.py`, and the minimal current-state notes in `.ai/03_common_handoff.md` / `.ai/05_pipeline_contracts.md` if warranted. Run the focused mapping tests, combined lexical tests, and `scripts/quality.ps1`; report actual outcomes and any environment limitation. Report the exact changed files and the corrected invariant. Stop with L05 awaiting review and explicit user acceptance; do not implement L06.

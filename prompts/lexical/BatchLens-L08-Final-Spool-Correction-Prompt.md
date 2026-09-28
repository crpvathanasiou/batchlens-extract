# BatchLens — L08 final focused spool correction

## State and scope

L01–L07 are user-accepted. L08 and its ordering/bounds/completion correction are implemented and test-verified, but L08 is not yet user-accepted. Correct **only** the two remaining spool-path issues below. Read current `AGENTS.md`, `.ai/03_common_handoff.md`, relevant `.ai/05_pipeline_contracts.md`, `dictionary_aggregation.py`, and focused tests. The current repository is authoritative. Do not start L09 or alter L01–L07, candidate grouping, `supporting_row_ids`, result contracts, snapshot, review UI, or other application behavior.

## Required corrections

1. `_ingest_discoveries` calls `connection.commit()` after its per-insert `sqlite3.Error` handler; a commit failure currently escapes as a raw `sqlite3.Error`. Translate it to bounded `DictionaryAggregationError(SPOOL_WRITE_FAILED)`, preserve cleanup and no-coverage semantics, and test an injected commit failure after otherwise valid discoveries. Do not mislabel an upstream L07 read failure as a spool write failure.

2. `_require_block_capacity` executes `SELECT COUNT(*) ... WHERE block_node_id = ?` **for every discovery**. For a block with `h` hits, repeated range counts scan approximately `1 + ... + h` existing entries, creating quadratic work up to the configured block limit. Use a small disk-backed per-block counter in the same temporary SQLite spool, updated with each inserted discovery, so capacity checking remains bounded in memory and does not repeatedly count all prior hits. Keep the existing `LIMIT result_buffer_records + 1` read guard as a defensive check. Ensure the counter and discovery insertion cannot diverge on an error (one transaction or equivalent rollback/fail-closed behavior). Keep overflow explicit without truncation. Test a repeated-hit block at the threshold and one above it; verify the corrected path does not issue a full per-hit `COUNT(*)` against `discoveries`. No framework or new persistent table in the knowledge snapshot.

## Verification and stop

Permitted changes: `src/app/lexical_extraction/dictionary_aggregation.py`, `tests/lexical_extraction/test_dictionary_aggregation.py`, and concise factual updates to `.ai/03_common_handoff.md` / `.ai/05_pipeline_contracts.md` if necessary. Run focused L08 tests, the lexical suite, and `scripts/quality.ps1`; report exact results and any actual failure. The early full-Materials time/peak-memory measurement remains unverified until a newly exported reviewed HTML v1 path is available; do not substitute conversion HTML or infer performance from synthetic tests.

Stop after this L08 correction. Return the changed files, relevant error and counter lifecycle behavior, test evidence, and remaining limitations. Await explicit L08 acceptance before any next task.

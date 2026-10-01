# BatchLens — L04 focused provenance correction

L04 is **implemented and test-verified according to Cursor's report**, but it is not user-accepted. Correct only the two preflight provenance gaps below. Preserve the existing read-only handle, bounded pagination, lookup, and L01–L03 behavior. Do not implement L05 or later work.

## Independent findings

I inspected `src/app/lexical_extraction/knowledge_snapshot.py` and reproduced these cases against a small synthetic snapshot constructed from the supplied L04 test fixture:

1. `manifest.flat_schema_version = true` was **accepted** as integer schema version `1`. So was `manifest.database.user_version = true`. `_require_exact()` uses Python equality, where `True == 1`.
2. Replacing only `manifest.snapshot_id` with `"flat-v1-unrelated"` was **accepted**, even though `snapshot_identity` and all four source hashes were unchanged. The producer derives the ID as `flat-v1-` plus the first 20 lowercase hex characters of SHA-256 of `json.dumps(snapshot_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")`. The supplied production manifest does satisfy this derivation.

These are metadata validation failures, not evidence of a database write or a failed production smoke check. I did not rerun Cursor's full quality gate or access the 441 MB database here.

## Required correction

- Enforce **strict JSON integer types** for every schema/user-version equality check in the manifest and its `snapshot_identity`/database record. Reject Booleans, floats, and numeric strings even when Python equality would compare them to `1`. Preserve the existing error boundary (`SnapshotReadError`, stable bounded code/message) and do not alter L01's `KnowledgeSnapshotIdentity`.
- Recompute the producer's `snapshot_id` from the validated `snapshot_identity` and require exact agreement with the manifest. Ensure the identity contains exactly the four expected ordered source names/hashes in producer order; a reordered or altered list must not be silently assigned the same ID. Do not require the filesystem directory name to equal `snapshot_id`, because a validated snapshot may be mounted/copied under another path. Do not compare historical producer-code hash or contract text with current repository files.
- Keep preflight read-only and once per handle. These failures must occur before returning a `KnowledgeSnapshot` or provenance identity, without touching original CSVs or rebuilding the snapshot.

## Verification and stop

Extend `tests/lexical_extraction/test_knowledge_snapshot.py` with regressions for Boolean root schema version, Boolean identity schema version, Boolean database user version, mismatched snapshot ID, and reordered source identity. Update the synthetic fixture to use a correctly derived producer-format snapshot ID; keep a positive check using the provided production manifest shape without needing the large database. Verify that the real snapshot still passes the bounded read-only smoke check **if locally available**, and report it accurately rather than assuming.

Run focused L04 tests, the combined lexical suite, and `scripts/quality.ps1`; report actual commands and results. Make only necessary, concise corrections to `.ai/03_common_handoff.md` and `.ai/05_pipeline_contracts.md` for validation behavior and current verification. Keep L04 awaiting user review. **Stop after this correction. Do not advance to L05.**

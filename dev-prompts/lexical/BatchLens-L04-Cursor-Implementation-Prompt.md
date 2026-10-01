# BatchLens — L04: Read-only Flat SQLite Snapshot Access

## 1. Authorization and stop boundary

L01 contracts, L02 configuration, and the corrected L03 reviewed HTML reader are **user-accepted**. Implement **L04 only**: one shared preflight of the existing flat SQLite snapshot, a pinned read-only connection, bounded single-table pagination, and indexed source `row_id` lookup. Add focused tests and update the execution-state documentation. This task does not extract terms or interpret business fields.

Stop after the L04 completion report. Do not implement the later fixed per-table search-field mapping, dictionary normalization, matching/Aho–Corasick, fuzzy matching, value parsing, component orchestration, runner/CLI, monitoring, or publication. Do not proceed to L05.

## 2. Accepted baseline and required inspection

Repository: `C:\Users\User\batchlens-extract`. Inspect the actual working tree first. The supplied L03 report records 19 focused reader tests and a passing 327-test quality gate; these are recorded Cursor results, not your new verification. The user has now accepted L03. Keep L01/L02/L03 behavior intact.

Read before editing:

1. `AGENTS.md` and current `.ai/03_common_handoff.md`; relevant `.ai/02_code_quality_standards.md`, `.ai/00_project_reference.md`, `.ai/01_implementation_roadmap.md`, `.ai/04_code_map.md`, and `.ai/05_pipeline_contracts.md`.
2. `docs/FLAT_SQLITE_CONTRACT.md`; the existing publisher `scripts/prepare_lexical_knowledge_sqlite.py` only for snapshot format, identity, validation, and read-only query conventions; its focused tests for realistic synthetic snapshots.
3. `src/app/lexical_extraction/contracts.py`, especially `KnowledgeSnapshotIdentity` and `SafeStructuredError`; `configuration.py`, especially `KnowledgePaths` and `ResourceLimits`; the L03 reader's failure/completion boundary.
4. The published local snapshot's `manifest.json`, `validation_report.json`, and historical `FLAT_SQLITE_CONTRACT.md`, if available. The production `knowledge.sqlite` remains on the user's local machine; do not require it in the GPT environment or request CSVs. Check `pyproject.toml` and `scripts/quality.ps1`.

The maintained flat contract's example SQL and older prose mention some search fields that were subsequently superseded. L04 reads flat rows without selecting lexical/business fields. Do **not** treat its Greek, brand/model, or published-range examples as authorization to match them; fixed V1 mapping is a later task. Likewise, no language-filtering subsystem belongs here.

## 3. Snapshot preflight and provenance

Expose one small public boundary taking the L02 resolved `snapshot_directory` (plus bounded read-batch/cache values, directly or through a thin config adapter). Successful preflight provides a read-only snapshot handle and the existing L01 `KnowledgeSnapshotIdentity`:

- `snapshot_id`, `preparation_version="flat-sqlite-1"`, strict schema/user version `1`;
- `database_sha256` verified against the actual `knowledge.sqlite` bytes and manifest;
- `manifest_sha256` of the exact `manifest.json` bytes used for validation.

Validate **once per snapshot handle/run**, before any catalogue scan:

- All four snapshot companions exist and are readable: `knowledge.sqlite`, `manifest.json`, `validation_report.json`, and the snapshot's **nonempty** `FLAT_SQLITE_CONTRACT.md`. Do not replace the historical contract with the newer repository file or compare their text/producer hash for equality.
- Manifest and report are JSON objects of the expected shape. Require `completion_status="complete"`, flat schema/version and database filename/size/hash/user-version coherence, a snapshot ID and snapshot identity consistent with the four sources, and exactly the four expected source table names. Verify report integrity/content-digest/source-preservation/WAL-absence evidence and its table names, column names/counts and imported row counts against the manifest. Use strict types for status/count/Boolean checks; do not accept stringified values as proof.
- Inspect the actual SQLite file through a correctly encoded `file:` URI with `mode=ro`, then set `PRAGMA query_only=ON`. Require `PRAGMA user_version=1`, `PRAGMA integrity_check` returning `ok`, exactly the four expected rowid tables with the **fixed v1 source headers in `docs/FLAT_SQLITE_CONTRACT.md`** in order (and agreement with manifest/report), `TEXT NOT NULL` values plus source `row_id` as the primary key, and compatible reported row counts. A table's source `row_id` is not the SQLite `rowid` pagination cursor. Do not assume native/grouping IDs in other columns are unique or nonempty.
- Reject missing/incompatible companions, schema/hash/count/integrity mismatch, or present WAL sidecar as a structured input error. Do not repair, migrate, reimport, or rebuild. Do not require original CSV paths named in the manifest to exist. The snapshot directory and all provenance used by the handle must be pinned to this one validated build; report a detectable mid-read change as an error rather than silently mixing builds. Keep companion parsing small and database hashing streamed in finite chunks, never `read_bytes()` for the 441 MB file.

Use a focused `SnapshotReadError` or equivalent with stable bounded codes/messages mappable to `SafeStructuredError`. Close connections on validation failures, caller exit, and read errors. No successful validation claim on failure. Do not couple the lexical reader to the preparation script's `prepare()` flow or import-side effects; copying a tiny pure convention is preferable to reusing its orchestration.

## 4. Read-only query API

Expose a minimal allowlisted API for **only** `materials_fda_ema`, `materials_chebi`, `equipment`, and `unit_operations`. It should permit a later component to request one table, without scanning unrelated tables' vocabulary. Preflight of the shared snapshot still validates all four tables; equipment-only execution later must not page through Materials rows.

- Page by SQLite `rowid > :after_rowid ORDER BY rowid LIMIT :batch_size`, beginning at zero and advancing to the last returned `scan_cursor`. Fetch no more than the validated L02 `sqlite_read_batch_rows` limit per query. Yield bounded batches or rows with the cursor and original source columns as unchanged `str` values (including empty strings, Unicode, punctuation, whitespace, and literal `FALSE`/`N/A`). Do not materialize the whole table or deduplicate repeated source rows.
- Lookup a source record by **existing `row_id`** in the same table using its indexed primary key, returning the exact source row or an explicit absent result. Keep `scan_cursor` distinct and local to this snapshot. Quote table/column identifiers safely from the fixed allowlist and parameterize values; do not concatenate caller-controlled identifiers or `row_id` into SQL. No joins, normalized tables, added indexes, temporary writes, or extra persistent catalogue.
- Return a small raw row/batch representation, not L01 dictionary candidates or output business records. Do not copy all columns into final extraction results. The fixed field interpretation, eligibility (`Index this row` versus independently eligible process steps), alias qualifications, UNII boundaries, and source-specific IDs are **L05 work**, not an L04 mini mapping framework.
- Apply L02's finite SQLite cache setting without introducing WAL or writes. Preserve one clear connection/snapshot lifecycle and deterministic scan order. A scan/lookup attempted before successful preflight or after close fails explicitly.

## 5. Permitted changes

Create `src/app/lexical_extraction/knowledge_snapshot.py` (or one comparably focused module) and `tests/lexical_extraction/test_knowledge_snapshot.py`. A small synthetic flat SQLite fixture and its companion JSON/contract files may be constructed inside tests. Minimal package re-exports are permitted if repository convention calls for them.

Update `.ai/03_common_handoff.md` as the state anchor and concise relevant entries in `.ai/01_implementation_roadmap.md`, `.ai/04_code_map.md`, and `.ai/05_pipeline_contracts.md`. Mark L03 user-accepted, record L04's actual results and remaining work. If an existing contract document must be clarified to avoid an L04 ambiguity, keep the change narrow and preserve the historical snapshot copy; do not silently rewrite the locked L05 field decisions.

Do not alter L01/L02/L03, the renderer, review UI, snapshot/database/companions, preparation behavior, original CSVs, or unrelated infrastructure. Avoid adding dependencies; `sqlite3`, `json`, `hashlib`, and `pathlib` are available in the standard library.

## 6. Meaningful verification

Synthetic fixtures should cover:

1. Successful complete four-table snapshot, exact `KnowledgeSnapshotIdentity` and manifest hash, read-only connection, all companions, rowid-table schema, and stable cleanup.
2. Pagination across boundaries and an empty final batch; distinct `scan_cursor` versus text `row_id`; exact retrieval by `row_id`; absent lookup; preservation of source strings, optional blanks, duplicates in non-`row_id` columns, and Greek Unicode **as stored** (not as a search-term decision).
3. Invalid table name, invalid/oversize batch, attempts before preflight/after close, safe parameterization, and no cross-table scan when a caller requests only one table.
4. Missing/blank companion, malformed JSON/report, wrong status/schema/user version, inconsistent source/table names, headers or counts, wrong DB size/hash, integrity failure/corrupt database, WAL sidecar, and no fallback to CSV or preparation. No write, journal, WAL, SHM, or new output file from the reader.
5. A held handle's use after a detectable snapshot replacement/change fails rather than claiming the old identity for new bytes. Test the practical pinning approach you implement without adding a per-row full-file hash.

If the already published local snapshot is available, perform **one read-only production smoke check** after the focused suite: preflight, two small pages per table and one `row_id` lookup per table, checking only that bounded access works. Compare database and companion hashes before/after and confirm no WAL/SHM sidecar; report timing of preflight separately from scan. This is not a repeat of data preparation, not pharmaceutical content acceptance, and not the later full-Materials matching measurement. If unavailable in the Cursor environment, report it as unverified; do not fabricate it or substitute CSVs.

Run focused snapshot tests, combined lexical tests, and `scripts/quality.ps1` in the supported environment. Report actual commands/results, environment blocks, and any read-only production check. Do not weaken gates or target an old test count.

## 7. Definition of Done and stop

L04 is complete when a later fixed field mapper can consume exactly one validated immutable flat snapshot, page only its requested allowlisted tables within configured limits, and resolve original `row_id` references without modifying the database or disguising an incompatible snapshot as zero matches.

Return the exact files changed; public preflight/handle/scan/lookup API and lifecycle; validations and `KnowledgeSnapshotIdentity` derivation; boundedness/read-only proof; focused/full-gate and any real-snapshot checks; documentation state; and explicit L05+ boundaries.

**Stop after L04. Await review and explicit user acceptance before producing or implementing L05.**

# BatchLens — L13 focused correction: bounded publication and exact evidence lookup

## Baseline and scope

L01–L12 are user-accepted. L13 is implemented and test-verified by the reported gates, but **awaiting user acceptance**. Correct the concrete L13 issues below only. Read `AGENTS.md`, current `.ai/03_common_handoff.md`, `src/app/lexical_extraction/{publication,runner,contracts,configuration}.py`, and `tests/lexical_extraction/test_publication.py` from the current repository. Preserve matching, L12 outcomes/sink semantics, partial publication, versioned schemas where compatible, CLI exit codes, manifest-last behavior, and the real-input report as historical evidence. Do not start the review UI or another milestone.

## 1. Keep serialization and artifact reading bounded

`FilesystemEvidenceSink._load_sorted_blocks()` currently loads every block on a physical page into a list; `_materialize_component_artifact()` then creates a tuple and a whole `PageRecord` for that page. A large page with many text/table blocks can grow without the L02 result-buffer limit. `_ComponentStaging` also retains `page_numbers`, `page_orders`, and `block_counts` for all pages. The staging files do not by themselves make this bounded.

Stream the page/block JSON artifact using only finite per-page/per-block working state and disk staging/indexing as needed. Preserve page order, block order, empty pages/blocks, Pydantic record validation at appropriate boundaries, exact evidence, and deterministic bytes apart from run ID. Reject duplicate or missing block/page identity and incomplete staging without committing a component. If the producer can emit blocks out of order, use a bounded external sort or a fail-closed explicit limit; do not silently reorder using an unbounded list. Do not reintroduce an all-document/all-page in-memory structure.

`iter_component_pages()` currently calls `artifact_path.read_text()` and `json.loads()` on the **entire component artifact** before yielding its first page. Replace it with a genuinely incremental reader, or provide a genuinely streaming replacement and update callers/docs accordingly. It must validate schema and yield bounded page/block records, with errors on truncation/malformed JSON. Avoid a new broad parsing framework; use a small format-compatible reader or a narrowly justified dependency if necessary. The test must demonstrate that the first page is available before the entire artifact is read, and that a large synthetic page/document does not build an unbounded list of records. Do not claim whole-document bounded reading if an in-memory full JSON parse remains.

## 2. Write all bytes, and hash the bytes actually published

`_materialize_component_artifact.write_raw()` currently calls `os.write(fd, chunk)` once and increments the digest/byte count by `len(chunk)` without checking the returned byte count. A short write could produce a truncated component artifact whose descriptor hashes the intended bytes rather than the file, while a manifest still claims success. Use a checked write-all loop (zero/failed write is an error), or a buffered file writer with checked flush/close; compute/check size and SHA-256 from the actual completed file before atomic commit. Ensure any write/fsync/rename failure cannot leave a completed component or final manifest claiming valid publication. Add a targeted short-write/failure regression; no large-file benchmark is needed.

## 3. Return a hit only for the requested span

`locate_hit()` currently returns `(page, block)` after finding the `node_id` even if **none** of the block's occurrence spans matches `(start_char, end_char)`. Return `None` for the wrong span or an empty block, and return the correct page/block for a genuine match. Preserve the full L01 span check, including nested value/unit spans if that is the documented lookup behavior. Test correct page and node with a wrong span, correct span on the wrong node, empty block, and an actual hit.

## 4. Protect the read-only snapshot from an output-path mistake

The CLI takes `output.directory` from YAML, and the filesystem sink creates its run folder there. Reject an output root equal to or inside the configured snapshot directory **before `begin_run` creates any directory**, using resolved path containment rather than string-prefix matching. This is necessary for the stated L13 guarantee that publication never writes to the snapshot. An ordinary sibling output directory remains valid. Do not require privileged hardware or filesystem access. Add a focused configuration/run test showing that an output path nested inside the snapshot is refused without changing snapshot contents or creating a run directory.

## Verification and stop

Keep existing L13 cases passing: completed and partial runs, completed-zero, manifest-last failure, hash verification, prior-run preservation, combined/full selection, exact page/node offsets, and CLI status. Add focused regressions above, including a multi-page fixture with a page carrying enough blocks to expose whole-page materialization. Run focused `tests/lexical_extraction/test_publication.py`, combined `tests/lexical_extraction/`, and `scripts/quality.ps1`; report **actual** outputs. A second full production Materials/full run is not required for these corrections. Update `.ai/03_common_handoff.md` as the state anchor and `.ai/05_pipeline_contracts.md` / `.ai/04_code_map.md` only where claims or public behavior change. Preserve the earlier 169.257 s real-input report as historical, not as verification of the corrected code.

Return changed files, the bounded write/read approach, short-write and lookup outcomes, snapshot-path guard, actual tests, and remaining limits. Mark L13 **awaiting user acceptance**. **Stop before the review UI, human approval, vector/LLM work, or any later task.**

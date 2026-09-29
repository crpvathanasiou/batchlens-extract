# BatchLens — Stage 2: Detailed Design and Local Execution Guide

This guide explains the implemented Stage 2 lexical extraction engine and how to run it on a local Windows machine. The short introduction is `docs/BatchLens-Stage2-Lexical-Extraction-Overview-EN.md`. This document adds prerequisites, configuration, the execution sequence, artifacts, verification, and recovery.

The audience is a developer, or another LLM starting a new session, who needs to follow the local flow without prior context. The description follows the current code. Recorded quality gates and the user-accepted L01–L13 boundary come from the project handoff. Commands in section 7 are for a later run. They were not executed while this guide was written.

Stage 2 is a local, deterministic evidence extractor. It searches a reviewed HTML v1 file with a pinned, read-only flat SQLite catalogue snapshot and writes a new run directory. A match records that a catalogue spelling, alias, code, or controlled value form occurred in a specific block. It does not establish a pharmaceutical fact, prove that a batch was executed, or decide that two mentions belong together.

## 1. Scope and current status

Stage 2 starts when an operator supplies three local things: one reviewed HTML v1 file, one flat snapshot directory, and one YAML execution file. It ends when the process returns. If publication completes, the output directory contains a new `{run_id}` folder, one JSON artifact for each completed component, and a final `manifest.json` written last.

The operational workflow is expected to supply an HTML file that a person already approved and exported in Stage 1. The engine does not query a review store, an approvals database, or an “Approved Documents” folder. It validates the HTML v1 structural contract and the producer attributes on the `<html>` element, then records a SHA-256 of the exact bytes it finished reading. Those checks identify the file that was read. They do not prove that a human approval is still current.

Document-review approval is approval of a reviewed document revision. It is not manufacturing batch release, not approval of these lexical findings, and not a regulatory electronic signature.

| Label | What it means for Stage 2 |
|---|---|
| **implemented** | L01–L13 exist under `src/app/lexical_extraction/`: contracts, configuration, HTML reader, snapshot reader, field mapping, comparison, matching, aggregation, units and values, runner, monitoring, filesystem publication, and the CLI. |
| **test-verified** | Recorded gates on 2026-09-28: focused `tests/lexical_extraction/test_publication.py` 26 passed; `tests/lexical_extraction/` 278 passed; `scripts/quality.ps1` passed (Ruff, Pyright clean, pytest 548 passed). This documentation task did not re-run those gates. |
| **user-accepted** | L01–L13 are the accepted Stage 2 baseline for this guide. `.ai/03_common_handoff.md` and `.ai/01_implementation_roadmap.md` may still say that L13 awaits acceptance. That wording predates the acceptance decision and was left unchanged. |
| **unverified** | Pharmaceutical precision or recall, human acceptance of individual findings, an Extraction Review Workspace, and any command in section 7. The historical 169.257-second full run is programmatic evidence for an older publisher; it does not verify the later streaming-reader correction. |

Stage 2 does not provide a review, edit, or approval UI for findings. It does not run an LLM, a vector index, a graph, or association logic. Later milestones that would add those capabilities are outside this engine.

A PDF, an unreviewed conversion HTML file, `document.json`, or a review JSON file is not a lexical input. The only document input is reviewed HTML contract version `"1"`.

## 2. Components and responsibilities

Configuration chooses paths, the component set, the fuzzy switch, and finite resource limits. It does not choose the matcher, the normalization rules, or the catalogue columns. The runner then validates the HTML, prefights the snapshot, executes the resolved components, and streams evidence to a filesystem sink. The sink commits component artifacts and, only after the runner returns cleanly, writes `manifest.json` last.

```text
execution.yaml
    → configuration load, preset union, effective digest
    → reviewed HTML v1 full read (byte SHA-256 + producer metadata)
    → snapshot preflight (read-only connection)
    → dictionary components, one independent pass each
         field map → bounded shards / replay → aggregate → stage
    → parameter / unit / value components, one shared pass when selected
    → per completed component: artifacts/component-<name>.json
    → seal, then manifest.json
```

| Responsibility | Principal path | Role in one local run |
|---|---|---|
| Evidence records | `src/app/lexical_extraction/contracts.py` | Page, block, span, candidate, unit, value, outcome, and publication records. Schema `batchlens.lexical-record.v1`. Importing the package does no I/O. |
| Execution YAML | `src/app/lexical_extraction/configuration.py` | Strict YAML load, preset union, resource bounds, effective SHA-256. Does not create directories or open the HTML or snapshot. |
| Reviewed HTML | `src/app/lexical_extraction/html_reader.py` | Streams reviewed HTML v1 into pages and blocks. Final file identity exists only after a complete read. |
| Snapshot | `src/app/lexical_extraction/knowledge_snapshot.py` | Preflight and read-only paging / `row_id` lookup. Cells stay stored text. |
| Field mapping | `src/app/lexical_extraction/field_mapping.py` | Fixed V1 columns become eligible search terms for the selected components. |
| Comparison | `src/app/lexical_extraction/comparison.py` | Fixed normalization, original-offset projection, and boundary checks. |
| Dictionary match | `src/app/lexical_extraction/dictionary_matcher.py`, `fuzzy_matching.py` | Bounded Aho–Corasick exact and normalization-aware hits. Optional distance-1 fuzzy hits when enabled. |
| Dictionary aggregation | `src/app/lexical_extraction/dictionary_aggregation.py` | Groups hits by block and span, reloads catalogue rows, emits block records. |
| Units and values | `unit_value_rules.py`, `unit_aggregation.py`, `value_expressions.py`, `parameter_unit_value.py` | Independent parameter-name, unit, and value recognition. |
| Runner and monitoring | `runner.py`, `monitoring.py` | Callable run boundary, outcomes, and in-memory counters. |
| Publication and CLI | `publication.py`, `__main__.py` | Run directory, atomic artifacts, final manifest, process exit code. |
| HTML producer | `src/app/document_review/rendering.py` | Writes the reviewed HTML attributes Stage 2 later checks. Stage 1 execution is outside this guide. |

The runner is a local function call. The CLI is a local process:

`poetry run python -m app.lexical_extraction --config <execution.yaml>`

There is no job queue, resume service, or background worker. The process runs until it returns or the operator stops it.

### Bounds, shards, replay, and temporary files

Resource limits are the integers in the YAML `resources` section. The engine does not measure host RAM and does not size shards, caches, or buffers from available memory. After the run, monitoring may report peak process memory. That number describes the process that already ran. It is not an input to the next run.

| Configured limit | Operational effect |
|---|---|
| `sqlite_read_batch_rows` | Maximum rows requested in one snapshot page (`rowid` pagination). |
| `sqlite_cache_kib` | SQLite cache size for the read-only connection, in kibibytes (`PRAGMA cache_size` with a negative KiB value). |
| `max_terms_per_shard` | Maximum source references retained in one match shard. |
| `max_term_codepoints_per_shard` | Maximum retained term text, in Unicode code points, including fuzzy deletion-signature storage when fuzzy matching is on. |
| `result_buffer_records` | Maximum discovery records emitted in one buffer, and the per-block capacity guard during aggregation. |

Eligible terms are consumed once and packed into finite shards. Each shard builds an automaton, rescans the document blocks, emits hits, and then releases that shard. A smaller shard limit can cause more rescans. For the same pinned HTML and the same terms, the multiset of discoveries does not depend on the shard limit. Emission order may follow shard order.

Reviewed HTML is reopened for each pass. The first complete validation pins `html_sha256`. A later pass that sees different bytes fails that pass. The reader keeps the current page, a short queue, and identity sets. It does not keep the whole file or every page in memory. `read_all_pages` is a test helper, not the production path.

Dictionary aggregation writes a temporary SQLite spool (`batchlens-l08-spool-*` under the system temporary directory, `PRAGMA temp_store=FILE`). Unit aggregation uses a separate spool (`batchlens-l10-unit-spool-*`). On a successful finished stream, the spool connection is closed and the temporary directory is deleted. If that deletion fails, the component does not receive completed coverage (`SPOOL_CLEANUP_FAILED`). Closing a stream early releases the spool and does not publish coverage.

Publication staging lives under `{output}/{run_id}/.staging/<component>/`. Page order is stored in per-page `.meta` files; block text is stored as JSONL. After a component artifact is committed, that component’s staging directory is removed. Aborting an uncommitted component removes its staging. Temporary artifact and manifest files are created beside the destination, fsynced, and atomically renamed. A failed write deletes the temporary file. `manifest.json` is not left behind as a completed publication when that write or rename fails.

A discarded staging delete ignores filesystem errors. A leftover `.staging` directory, if a delete could not finish, is not an extra published result. The published claim is `manifest.json` plus the artifact files it lists.

## 3. Inputs, configuration, outputs, and local data boundaries

Paths in the YAML are resolved against the directory that contains the YAML file, not against the shell’s current directory. Absolute paths are kept. The loader does not require the paths to exist and does not create them. Empty strings are rejected.

The checked-in example `examples/lexical_extraction/execution-config.example.yaml` uses relative placeholders (`./inputs/reviewed.html`, `./knowledge/flat-v1`, `./results`). Those placeholders are not real data in this repository. Copy the example and replace the three paths. Leave the example file itself unchanged.

| Artifact | Producer / owner | Consumer | Purpose | Identity and validation | Read / write | Protected content |
|---|---|---|---|---|---|---|
| Reviewed HTML v1 | Stage 1 review renderer, supplied by the operator | HTML reader and every replay | Document text, pages, blocks, node ids, OCR references | Root `data-review-html-version` must be exactly `"1"`. Requires `data-job-id`, `data-review-revision-id`, `data-review-generation`, and `data-conversion-status` (`SUCCEEDED` or `PARTIAL_SUCCESS`). Final `html_sha256` is SHA-256 of the exact bytes parsed, and only after a complete read. | Read-only | Yes. Manufacturing document text. |
| `knowledge.sqlite` | Snapshot preparation, outside this engine | Snapshot reader | Four flat tables: `materials_fda_ema`, `materials_chebi`, `equipment`, `unit_operations` | Opened with `mode=ro` and `PRAGMA query_only=ON`. Journal mode must be `delete`. User version must be integer `1`. Row counts must match the manifest. | Read-only | Yes. Catalogue terms and identifiers. |
| `manifest.json` inside the snapshot directory | Snapshot preparation | Preflight | Snapshot id, file name, size, hash, schema, preparation version, row counts | `completion_status` must be `complete`. Schema version must be the JSON integer `1`. `snapshot_id` must match the producer derivation (`flat-v1-` plus 20 hex characters). | Read-only | Yes. Catalogue identity and counts. |
| `validation_report.json` | Snapshot preparation | Preflight | Integrity, content digest, source preservation, WAL absence, table shapes | `integrity_check` must be `ok`. WAL-absence and companion flags must be boolean true. Column lists and row counts must match the fixed v1 contract and the manifest. | Read-only | Yes. |
| Snapshot `FLAT_SQLITE_CONTRACT.md` | Copied at snapshot preparation | Preflight | Contract text stored with that snapshot | Must exist and be non-empty. The engine does not compare it with a later copy of `docs/FLAT_SQLITE_CONTRACT.md`. | Read-only | The contract text itself is technical. Keep it with the snapshot. |
| Execution YAML | Operator, from the example | Configuration loader and CLI | Paths, selection, fuzzy switch, resource limits | Schema version integer `1`. Unknown keys, unsafe YAML, and out-of-range limits fail before search. | Read-only at run time | May name protected paths. Do not commit a working copy that points at private data. |
| Effective configuration digest | Computed by the loader | Run provenance `configuration_sha256` | Stable identity of the operational settings | Lower-case SHA-256 of canonical JSON: absolute paths, sorted preset and component names, resolved component order, fuzzy flag, resources. List order in the YAML does not change the digest. | Computed, not a separate file | Contains absolute paths. |
| `{output}/{run_id}/artifacts/component-<name>.json` | Publication, one file per completed component | Later inspection; future review workspace | Pages, original block text, occurrences, spans | Schema `batchlens.lexical-component-artifact.v1`. SHA-256 and byte size are taken from the completed file before the atomic rename. | Created once. Not replaced. | Yes. Copies block text and matched literals. |
| `{output}/{run_id}/manifest.json` | `finalize_publication`, last | Operator checks; `load_final_manifest` | Identities, outcomes, monitoring, artifact hashes | Schema `batchlens.lexical-run-manifest.v1`. Written only for a sealed run with validated HTML, snapshot, provenance, and extraction outcomes. The manifest is not hashed as if its own bytes were already known. | Created once | Yes. Includes paths, hashes, and counts. Block text lives in the artifacts. |
| `.staging/` and spool files | Publisher and aggregators | The same run | Provisional pages and discovery grouping | Staging is under the run directory. Spools are system temp directories. | Deleted on the success paths described in section 2. An interrupted run may leave them. | Yes, while they exist. They are not a final result. |

`examples/lexical_extraction/result-example.json` is a small synthetic contract fixture. It is not the output of a local run.

### YAML shape

Required top-level keys, and no others: `schema_version`, `input`, `knowledge`, `output`, `extraction`, `resources`.

```yaml
schema_version: 1
input:
  reviewed_html_path: <nonempty path>
knowledge:
  snapshot_directory: <nonempty path>
output:
  directory: <nonempty path>
extraction:
  presets: [<preset name>, ...]
  components: [<component name>, ...]
  fuzzy_enabled: false
resources:
  sqlite_read_batch_rows: 5000
  sqlite_cache_kib: 65536
  max_terms_per_shard: 2000000
  max_term_codepoints_per_shard: 50000000
  result_buffer_records: 50000
```

`schema_version` must be the integer `1`. The string `"1"`, a float, or a boolean is rejected.

`input` allows only `reviewed_html_path`. `knowledge` allows only `snapshot_directory`. `output` allows only `directory`. Each value must be a nonempty string.

`extraction` allows only `presets`, `components`, and `fuzzy_enabled`. Both lists are optional and default to empty, but at least one preset or one component is required. Entries are strings. Duplicates in either list are rejected. Unknown names are rejected. `fuzzy_enabled` may be omitted and then defaults to `false`. When present, it must be a YAML boolean (`true` or `false`). The string `"true"` and the number `1` are rejected.

`resources` may be an empty mapping. Omitted keys use the defaults below. Present values must be strict integers from 1 through the maximum. `0`, a value above the maximum, and a quoted number such as `"5000"` are rejected.

| Key | Default | Maximum |
|---|---:|---:|
| `sqlite_read_batch_rows` | 5000 | 100000 |
| `sqlite_cache_kib` | 65536 | 1048576 |
| `max_terms_per_shard` | 2000000 | 10000000 |
| `max_term_codepoints_per_shard` | 50000000 | 500000000 |
| `result_buffer_records` | 50000 | 1000000 |

The loader also rejects a second YAML document, a non-mapping root, duplicate keys, merge keys (`<<`), anchors and aliases, and tags outside the plain YAML null, bool, int, float, str, sequence, and mapping tags.

### Overrides

The CLI accepts only `--config`. It does not accept selection flags.

A Python caller of `load_execution_configuration` or `run_lexical_extraction_from_config_path` may pass a `SelectionOverride`. A provided `presets`, `components`, or `fuzzy_enabled` value replaces that YAML field entirely. An omitted override field keeps the YAML value. Override lists do not append to the YAML lists. The CLI path does not pass an override, so a local operator changes the YAML.

### Directory relationships

```text
<snapshot directory>/          read-only; never the output parent
    knowledge.sqlite
    manifest.json
    validation_report.json
    FLAT_SQLITE_CONTRACT.md
<working yaml directory>/      holds the copied execution file
<output directory>/            must not equal or lie inside the snapshot
    <new-uuid>/
        manifest.json
        artifacts/component-<name>.json
        .staging/              provisional; removed on the success path
```

Resolved output that equals the snapshot directory, or that is contained by it, is refused before any run directory is created (`OUTPUT_INSIDE_SNAPSHOT`). The snapshot directory name does not have to equal `snapshot_id`.

Git already ignores `out/`, `manual-input/`, `.local-review-data/`, `.venv/`, and `.env`. Put working YAML files and run directories under `out/` so they stay untracked. Reviewed HTML, snapshot databases, and published artifacts can contain manufacturing and catalogue text. Do not commit them.

Do not edit the source HTML, any snapshot file, a published manifest, or an older run’s JSON in order to force a result. A new question gets a new run directory.

## 4. Execution flow in detail

One CLI invocation loads the YAML, guards the output path, calls `run_lexical_extraction`, then calls `finalize_publication`. The same runner is what the tests call. Stopping the process stops the run. Nothing resumes it.

### 4.1 YAML, overrides, presets, digest

| | |
|---|---|
| Input | One YAML file. CLI: no override object. |
| Component | `configuration.py` via `publish_lexical_run` |
| Operation | Parse strict YAML, resolve relative paths, replace any Python override fields, union presets and direct components. |
| Output | `EffectiveExecutionConfiguration` and, later, `configuration_sha256`. |
| Continue when | The file is readable and the schema, selection, and limits validate. |

Resolved components always follow this order, keeping only the selected names:

`unit_operations`, `process_steps`, `materials`, `equipment`, `parameter_names`, `units`, `quantity_expressions`, `parameter_value_expressions`.

Overlapping presets and direct components are one union. The word `with` in a preset name means those components run in the same invocation. It does not create a link between them.

A configuration error prints `configuration_error=ConfigurationError` and `message=...` on stderr and returns exit code 3. No run directory is created. A missing `--config`, or an unknown CLI flag, is rejected by the argument parser before that table applies. The parser exits with status 2 and a usage message, and it does not print `extraction_status`.

### 4.2 Reviewed HTML v1

| | |
|---|---|
| Input | `input.reviewed_html_path` |
| Component | `html_reader.py`, called by the runner as a full validation pass |
| Operation | Stream bytes, decode UTF-8 incrementally, hash the bytes actually parsed, check the root attributes, emit pages and blocks, then discard them after counting. |
| Output | `ReviewedHtmlV1Input` with `html_sha256`, contract version 1, `job_id`, `review_revision_id`, `review_generation`, and `conversion_status`. Page and block counts are kept. The page list is not. |
| Continue when | The read completes and `completed` is true. |

The reader accepts source-bearing `p`, `h2`, `h3`, `h4`, `footer`, `td`, and `th` elements that sit under `article.element` and carry `data-node-id`. Empty cells are valid. Generated summary text and `Page N` headings are skipped. Bare non-whitespace text in an article, a missing node id, a node id outside a page, a mismatched table id, nested source markup, a truncated document, or a duplicate provenance attribute fails the read. `<br>` becomes a newline. Other source whitespace is kept.

`data-source-id` is split on ASCII spaces into ordered OCR references. An identifier that itself contains a space cannot be recovered from that attribute. The reader records the split; it does not repair the HTML.

Failure here is pre-validation. There is no validated HTML identity. The CLI summary says `extraction_status=pre_validation_failed` and `error_code=...`. Exit code is 2. Because the run directory is created at the start of the runner, an empty `{run_id}` directory may exist. It has no `manifest.json`. That directory is not a published run.

### 4.3 Snapshot preflight

| | |
|---|---|
| Input | `knowledge.snapshot_directory`, `sqlite_read_batch_rows`, `sqlite_cache_kib` |
| Component | `knowledge_snapshot.py` |
| Operation | Check the four companions, hashes, schema, row counts, journal mode, and sidecars. Open the database read-only. |
| Output | `KnowledgeSnapshotIdentity`: `snapshot_id`, `database_sha256`, `manifest_sha256`, schema user version 1, preparation version `flat-sqlite-1`. |
| Continue when | Preflight returns a handle. |

A `-wal`, `-shm`, or `-journal` file beside `knowledge.sqlite`, or a WAL header, fails with `WAL_PRESENT`. The engine does not delete sidecars, checkpoint, import CSV files, or rebuild the database.

If preflight fails, every requested component is `failed` with the snapshot error. The HTML identity from section 4.2 is kept in memory. Snapshot identity is absent, so no final manifest is written. Exit code is 3. The safe next action is to point at a snapshot directory that already passes preflight, and to start a new run. Do not repair the database from this guide.

After a successful open, each later read rechecks database size and modification time and re-hashes the three small companions. A change is `SNAPSHOT_CHANGED`: the connection closes and that read returns no rows under the previous identity.

### 4.4 Eligibility, comparison, and match discovery

| | |
|---|---|
| Input | Open snapshot, selected components, resource limits, pinned HTML hash, `fuzzy_enabled` |
| Components | Field mapping, comparison, dictionary matcher |
| Operation | Page only the tables needed by the selected components. Map non-blank cells to eligible terms. Shard those terms. Replay blocks from a reopened HTML file. Project hits back to original code-point spans and apply boundary rules. |
| Output | Streamed raw discoveries: method `exact`, `normalized_exact`, or `fuzzy`, original span, source table, field, and `row_id`. |
| Continue when | The shard finishes without an oversized term, a projection failure other than a normal boundary rejection, or an HTML identity change. |

`unit_operations`, `process_steps`, `materials`, and `equipment` each get their own mapping and match pass. A failure in one of those components is recorded on that component. Components that already completed stay completed. Components not yet started still run.

A single term that cannot fit in the configured code-point budget fails that component (`OVERSIZED_TERM`). Hits are not silently truncated. Colliding source rows are all kept.

If the HTML bytes change between the pinned validation and a replay, the pass fails (`REPLAY_IDENTITY_CHANGED` or the matcher’s equivalent identity failure). The run does not mix two documents into one component.

### 4.5 Aggregation, parameters, units, and values

| | |
|---|---|
| Input | Raw discoveries, replayed blocks, snapshot lookups, and, for values, the block text |
| Components | Dictionary aggregation; the shared parameter/unit/value composition |
| Operation | Spool discoveries, group them by block and original span, prefer `exact` over `normalized_exact` over `fuzzy` for the same span, collapse equivalent candidate interpretations to one representative `row_id` plus sorted `supporting_row_ids`, and reload each candidate with a single-table lookup. Recognize units and value expressions with the fixed V1 rules. |
| Output | Block records in document order, including blocks with no occurrences. |
| Continue when | The stream is fully consumed and spool cleanup succeeds. Coverage counts exist only then. |

Selected `parameter_names`, `units`, `quantity_expressions`, and `parameter_value_expressions` share one composition so a value expression is not duplicated. Parameter names use the dictionary path and may use fuzzy matching when the switch is on. Units and values never use fuzzy matching. A failure in that shared composition fails the L10 components that are still uncommitted. A component in the group that has already been committed stays completed.

Zero discoveries after a full successful stream is a completed component with match count 0. That is an empty result, not a failure.

### 4.6 Outcomes, monitoring, staging, and the final manifest

| | |
|---|---|
| Input | Component streams and the caller-owned filesystem sink |
| Components | `runner.py`, `monitoring.py`, `publication.py` |
| Operation | For each component: begin a provisional stream, write page skeletons from a fresh HTML read, write block records, then commit or abort. After every requested component has an outcome, seal the sink. If the runner returns without a run-level error, write `manifest.json`. |
| Output | `LexicalRunResult` in memory. On completed publication: artifact files and `manifest.json`. |
| Continue when | The sink is sealed, the run id matches, identities and provenance exist, no component is still provisional, and artifact files agree with completed outcomes. |

Overall status:

| Requested outcomes | Overall `run_status` | CLI exit if the manifest is written |
|---|---|---|
| Every requested component `completed` | `completed` | 0 |
| At least one completed or partial, and at least one not completed | `partial` | 1 |
| Every requested component `failed` | `failed` | 2 |

Unrequested components are recorded as `not_requested` and are omitted from the CLI summary. A partial run still publishes, and the manifest lists only the completed components’ artifacts. Completed counts inside that run stay usable.

Exit code 3 means publication did not complete, or the CLI failed before a sealed published run. There is then no `manifest.json` that claims completed publication. Component JSON files that were committed before a later publication failure can remain on disk. They are not a finished run until the manifest names them.

Stdout, when the runner returns, is a short summary: `run_id`, `extraction_status`, one `component.<name>=...` line per requested component, optional `run_error`, `publication_status`, peak memory, `manifest_path` or `publication_error`, and `exit_code`. The summary does not include block text or catalogue rows.

| Situation | What remains | What is not claimed | Safe next action |
|---|---|---|---|
| YAML or CLI configuration error | No new run directory from this attempt | No manifest | Fix the YAML. Run again. |
| Output path inside the snapshot | No run directory | No manifest. Stderr shows `cli_error=PublicationError` and exit 3 | Choose an output directory outside the snapshot. |
| HTML pre-validation failure | A run directory may exist with empty `artifacts/` and no manifest | Validated HTML identity and publication | Leave that directory. Fix the HTML path or file. Start another run. |
| Snapshot preflight failure | Run directory, no manifest. Requested components are failed in memory only | Snapshot identity and publication | Leave the snapshot unchanged. Use a directory that passes preflight. Start another run. |
| One component fails, others complete | Artifacts for the completed components, plus `manifest.json` with `run_status` `partial` | Success for the failed component | Read the failed component’s `error.code`. Start a new run after the cause is understood. Keep this run. |
| Every component fails after both identities exist | A manifest may exist with `run_status` `failed`, no component artifacts, exit 2 | Extraction success | Use the manifest’s error codes. Do not edit the run. |
| Manifest write or rename fails | Any artifacts already committed. No final manifest. Exit 3 | Completed publication | Leave the directory. Start a new run. |
| Process stopped mid-run | Whatever staging or artifacts were already flushed. No finalize step | A final manifest | Leave the directory. Start a new run. |
| HTML or snapshot bytes change during the run | Completed components that finished before the change, if publication then seals | A single identity for the interrupted component | Do not interpret a mixed read. Start a new run against stable files. |
| Zero matches | A normal artifact with pages, blocks, and empty occurrence lists. Count 0. Manifest if the rest succeeded | A failure, and also a pharmaceutical negative proof | Inspect the block text if you need to confirm the document really lacks that wording. |

## 5. Selection, matching, and interpretation rules

The operator selects presets and may also list components. Presets may be combined. The engine runs the union in the fixed order in section 4.1.

| Preset | Requested components |
|---|---|
| `unit_operations` | Unit operations only |
| `unit_operations_with_steps` | Unit operations and process steps |
| `materials` | Materials only |
| `materials_with_quantities` | Materials, quantity expressions and units |
| `equipment` | Equipment only |
| `equipment_with_parameters` | Equipment, parameter names, parameter-value expressions and units |
| `full` | All V1 components |

All eight component names, for a direct `components` list, are: `unit_operations`, `process_steps`, `materials`, `equipment`, `parameter_names`, `units`, `quantity_expressions`, `parameter_value_expressions`.

The operator can change:

- `extraction.presets` and `extraction.components`
- `extraction.fuzzy_enabled`
- the three paths
- the five resource integers, inside the maxima in section 3

The operator cannot change the matching algorithm, the normalization profile, which catalogue columns are searched, term-type rules, or individual method switches. Fuzzy matching is the only extraction switch, and it stays off unless `fuzzy_enabled` is `true`. Resource limits bound memory and shard size. They do not change the match rules.

### Fixed behaviour by family

**Materials.** FDA/EMA and ChEBI stay separate. Equal names do not merge a row from one table into the other. FDA/EMA search cells are `material_name`, `alias_name`, and `UNII`. ChEBI search cells are `material_name` and `alias_name`. CAS numbers are not searched. `SMS_ID` and `CHEBI_ID` are identities, not search cells. Blank cells produce no term. The markers `N/A`, `NA`, `unknown`, and `None` are skipped for UNII search and for optional native ids. They are not applied to material names or aliases, and those naming rows remain.

**Unit operations and process steps.** A `Search term (EN)` becomes a unit-operation term only when `Index this row` is the exact text `TRUE`. `Process step (EN)` is mapped independently of that flag. Support, inspection, and step-cue policies become generic cues. A generic cue has no invented operation id. An unrecognized nonempty match policy or record type fails field mapping for that row. Dedicated Greek fields are outside the unit-operation matching boundary.

**Equipment and parameters.** Equipment mentions come from `Equipment type (EN)`. Parameter names come from `Operating parameter (EN)`. A parameter candidate may carry the catalogue’s equipment type label. That label is scope stored on the parameter row. It is not a detected equipment mention in the document. Greek fields, brand, manufacturer, model, manufacturer and model ids, and published ranges are not search terms. A parameter name does not identify an equipment mention and does not fill in a number or a unit.

**Units.** Two sources are used together: the fixed quantity-unit vocabulary in `unit_value_rules.py` (`lexical-unit-vocabulary-v1`) and eligible atomic tokens from the equipment table’s `Unit` column. Placeholders, prose, spaced alternatives, ranges, and footnote markers are not eligible equipment-unit tokens. Compact tokens such as `mL/min` can be eligible. Units are matched with exact and normalization-aware token rules and `atomic_unit` boundaries. Accepted vocabulary aliases include case and token variants such as `ml` for `mL` and `ug` for `µg`. The artifact keeps the original document substring. Controlled spelling is a separate field. Units are never fuzzy-matched. A unit by itself does not identify a parameter, an equipment type, or an operation.

**Values.** Expressions are read from the document text. Forms are scalar-with-unit, range, comparison, symmetric tolerance, categorical (`OFF`, `under vacuum`), and cued unitless (`Speed:`). Numbers are exact finite decimal strings, or an explicit ambiguous token with no resolved value. `1,000` stays ambiguous. The engine does not convert units, bind a value to a parent material or parameter, or substitute a catalogue published range. Selecting a value component can recognize a unit inside an expression without also emitting a standalone unit occurrence. A standalone unit occurrence is emitted when `units` is selected. When both value components are selected, one occurrence lists both in `applies_to`.

### Exact, normalization-aware, and fuzzy matching

Ordinary hits are exact, or exact after the fixed comparison normalization. Each comparison unit is a Unicode starter plus its following combining marks, then NFC and casefold. That is not a whole-string NFC pass. Natural-language roles collapse a whitespace run to one separator. Material names, aliases, UNII codes, and units do not collapse whitespace and keep chemical punctuation, signs, digits, and unit superscripts. There is no stemming, NFKC, accent stripping, OCR hyphen repair, or cross-block joining. A hit must cover complete normalization units. Normalized indexes are not used as original offsets.

Boundaries are checked on the original characters beside the hit:

- Default and whole-code boundaries reject a hit that continues into letters, marks, decimal digits, connector punctuation, or a hyphen, so a shorter name or UNII is not taken from inside a longer token. A space-separated overlap at a word edge can still match.
- Atomic-unit boundaries also reject continuation through `/`, `·`, superscript signs, and numeric characters, so a shorter unit is not taken from inside a compound such as `min⁻¹` or `mL·min⁻¹`. A complete compound remains eligible. A unit may sit against an ordinary decimal number (`120rpm`, `37°C`).

Fuzzy matching, when `fuzzy_enabled` is true, applies only to an eligible single alphabetic word of at least six characters, at ordinary Levenshtein distance 1 (one insertion, deletion, or substitution). An adjacent transposition costs two and is rejected. Eligible roles are equipment type, parameter name, unit operation, and process step, and only when the fixed policy is not `context_required`, `step_cue_only`, `support_only`, or `inspection_only`. Fuzzy matching does not apply to materials, chemicals, UNII or other codes, generic cues, abbreviations, phrases, or units. A fuzzy candidate is a possible spelling neighbour. It is not confirmation that the catalogue row is the right reading of the document.

## 6. Evidence, artifacts, and result interpretation

A dictionary occurrence records:

- page number and page order
- block `node_id`, structural kind, exact block text, and optional element, table, and cell geometry
- ordered OCR references from `data-source-id`, which may be empty
- `location.start_char` and `location.end_char`, a zero-based half-open range of Unicode code points in that block’s text
- `location.matched_text`, which must equal `block.text[start_char:end_char]` with no trimming and no normalization
- `evidence.method`: `exact` (`lexical-v1-exact`), `normalized_exact` (`lexical-v1-normalized-exact`), or `fuzzy` (`lexical-v1-fuzzy`)
- one or more candidates, each with `candidate_kind`, source table, source field, `row_id`, `snapshot_id`, optional native ids, and `ambiguity` (`none`, `unresolved`, or `context_required`)
- `supporting_row_ids` when several equivalent rows share one interpretation

Repeated spellings stay. Overlapping spans stay. Several candidates on one span stay. `context_required` means the catalogue asked for more context. It is not a technical failure. Ambiguity is kept.

A unit occurrence has its own literal, span, and rule `lexical-v1-unit`. Provenance is either the fixed vocabulary or an `equipment_unit_record` with a representative `row_id` and any `supporting_row_ids`. It has no parameter id and no equipment-type id. Its evidence method is exact or normalization-aware exact.

A value occurrence has rule `lexical-v1-value`, a `form`, and `raw_expression` equal to the expression span. It does not carry dictionary candidates. Nested number and unit spans lie inside the expression. Dictionary method counts and unit or value counts are separate. Monitoring uses method keys `exact`, `normalized_exact`, and `fuzzy` for dictionary hits, and `unit` and `value` for the independent recognizers.

`Impeller speed: 120 rpm`, when the relevant components are selected, can produce three independent records: a parameter-name mention for `Impeller speed`, a value expression whose text includes `120 rpm`, and a unit mention for `rpm`. Those records do not say that the speed belongs to a particular impeller, or that 120 was an executed measurement. If the document instead contains only `rpm`, a unit-only run can record the unit and still have no parameter and no value.

A completed component with count 0 still publishes every page and block, with empty occurrence lists. A failed component publishes no artifact. A partial run’s manifest includes the completed artifacts and lists structured errors for the failed components. `monitoring.zero_result_components` names completed components whose count is 0. `monitoring.failed_components` names the failed ones. Omitted measurements mean the counter was not available. They are not stored as zero.

### Published layout

```text
<output directory>/<run_id>/
    manifest.json
    artifacts/component-unit_operations.json
    artifacts/component-process_steps.json
    artifacts/component-materials.json
    artifacts/component-equipment.json
    artifacts/component-parameter_names.json
    artifacts/component-units.json
    artifacts/component-quantity_expressions.json
    artifacts/component-parameter_value_expressions.json
```

Only completed components have files. Each artifact is one JSON object with `schema_version`, `record_schema_version`, `run_id`, `component`, `page_count`, and `pages`. Each page has a `page` object (`page_number`, `order`, `coverage`) and a `blocks` array. `coverage` value `complete` means the HTML page section was read. It does not mean the source PDF or OCR capture was complete.

`manifest.json` carries `validated_input`, `knowledge`, `provenance`, `extraction`, `publication`, `artifacts`, `monitoring`, `run_status`, and `errors`. Use it as follows:

- `validated_input.html_sha256` identifies the HTML bytes.
- `validated_input.job_id`, `review_revision_id`, `review_generation`, and `conversion_status` are the producer attributes from that file.
- `knowledge.snapshot_id`, `database_sha256`, and `manifest_sha256` identify the snapshot.
- `provenance.configuration_sha256` identifies the effective YAML, including absolute paths.
- `provenance.rules_sha256` identifies the fixed V1 rules actually used (`rules_version` `lexical-internal-rules-v1`).
- `provenance.fuzzy_requested` records the switch.
- `provenance.engine_version` and `dependency_versions` record the package versions seen for the engine and for `pyahocorasick`, `pydantic`, and `pyyaml` when those distributions are installed.
- `artifacts[].relative_path`, `byte_size`, and `sha256` identify each component file relative to the run directory.
- `publication.status` is `completed` only together with `publication.final_manifest`.

A manifest with `publication.status` `completed` means the publisher finished its file protocol. It does not mean a person approved the findings, and it does not mean the mentions are pharmaceutically correct.

Offsets are Unicode code points, the same indexing Python uses for `str`. A later browser highlighter must convert those offsets into the text or DOM positions that the browser uses. This guide does not implement that conversion. Do not treat the integers as UTF-16 code units or as raw byte offsets.

Do not hand-edit artifacts or the manifest. Hash checks exist so a change can be detected (`ARTIFACT_HASH_MISMATCH`, `ARTIFACT_SIZE_MISMATCH`).

## 7. Local execution guide — Windows PowerShell

Run the steps in order. Every command assumes the repository root unless the step says otherwise:

`C:\Users\User\batchlens-extract`

The example YAML’s relative paths are placeholders. This task did not execute the steps below and did not produce a new run. A historical reviewed HTML file and a historical snapshot directory were present on this machine at inspection; they are protected local data and are not written into the commands as defaults. Set the variables to the files you intend to read. Required files are listed in step 2.

### 7.1 Confirm Python and the locked environment

**Prerequisite.** Poetry is installed. The repository lockfile was generated by Poetry 2.2.1. `pyproject.toml` requires Python `>=3.11,<3.12`.

**Working directory.** `C:\Users\User\batchlens-extract`

```powershell
poetry --version
poetry run python -c "import sys; print(sys.version)"
```

**Expected.** `poetry --version` reports a Poetry 2.x installation. The Python line starts with `3.11`. This task found a `.venv` directory and did not run these commands, so it does not certify that the environment is complete.

**Initial install, only when `poetry run` reports that the environment or packages are missing.** Stay in the repository root. Do not upgrade packages.

```powershell
poetry install
```

**Expected.** Poetry installs from `poetry.lock` (PyYAML 6.0.3, pyahocorasick 2.3.1, pydantic 2.12.5, and the rest of the lockfile). An ordinary later run does not reinstall.

### 7.2 Set variables and check paths

**Prerequisite.** You already have one approved reviewed HTML v1 file and one flat snapshot directory. You will create a new output directory outside that snapshot.

**Working directory.** `C:\Users\User\batchlens-extract`

```powershell
$ReviewedHtml = "C:\path\to\reviewed-document.html"
$SnapshotDir  = "C:\path\to\flat-snapshot-directory"
$OutputDir    = "C:\Users\User\batchlens-extract\out\lexical-stage2\results"
$WorkDir      = "C:\Users\User\batchlens-extract\out\lexical-stage2"
$ConfigPath   = Join-Path $WorkDir "execution.yaml"
```

Replace only `$ReviewedHtml` and `$SnapshotDir`. Keep `$OutputDir` under `out\` so results stay gitignored, and keep it outside the snapshot. These are ordinary PowerShell variables for this task. Do not assign them to process-wide environment variables.

```powershell
Test-Path -LiteralPath $ReviewedHtml -PathType Leaf
Test-Path -LiteralPath (Join-Path $SnapshotDir "knowledge.sqlite") -PathType Leaf
Test-Path -LiteralPath (Join-Path $SnapshotDir "manifest.json") -PathType Leaf
Test-Path -LiteralPath (Join-Path $SnapshotDir "validation_report.json") -PathType Leaf
Test-Path -LiteralPath (Join-Path $SnapshotDir "FLAT_SQLITE_CONTRACT.md") -PathType Leaf
$outFull = [System.IO.Path]::GetFullPath($OutputDir)
$snapFull = [System.IO.Path]::GetFullPath($SnapshotDir)
$outFull.Equals($snapFull, [System.StringComparison]::OrdinalIgnoreCase)
$outFull.StartsWith($snapFull.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)
```

**Expected.** The five `Test-Path` results are `True`. Both containment results are `False`. If a snapshot companion is missing, stop. If either containment result is `True`, choose a different `$OutputDir`.

Optional read-only sidecar glance:

```powershell
Get-ChildItem -LiteralPath $SnapshotDir -Force -File | Where-Object { $_.Name -match 'knowledge\.sqlite-(wal|shm|journal)$' } | Select-Object Name
```

**Expected.** No rows. A sidecar row means preflight will refuse the snapshot. Leave the files in place.

### 7.3 Create a working configuration

**Prerequisite.** Step 7.2 passed. The checked-in example still has its placeholder paths.

**Working directory.** `C:\Users\User\batchlens-extract`

```powershell
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Copy-Item -LiteralPath ".\examples\lexical_extraction\execution-config.example.yaml" -Destination $ConfigPath
```

**Expected.** `out\lexical-stage2\execution.yaml` exists. `examples\lexical_extraction\execution-config.example.yaml` is unchanged.

Edit only the copy. Replace these three strings with the absolute paths in your variables:

- `input.reviewed_html_path`
- `knowledge.snapshot_directory`
- `output.directory` → the `$OutputDir` value

Relative paths in the copy would resolve under `out\lexical-stage2\`, because that is the YAML file’s directory. Absolute paths avoid that surprise. Do not point `output.directory` at the snapshot or at a previous run’s `{run_id}` folder. The output root may be new; the publisher creates `{run_id}` inside it. The loader will not create it during YAML parsing.

Leave `resources` at the example values unless you have a reason to lower a limit. Those values are the defaults. Do not exceed the maxima in section 3.

### 7.4 Choose a first selection

**Prerequisite.** The working YAML has the three real paths and still has `fuzzy_enabled: false`.

This is a local file edit. There is no extraction button in a UI.

| Intent | `extraction.presets` | `extraction.components` |
|---|---|---|
| Extract UOs | `[unit_operations_with_steps]` | `[]` |
| Extract Materials | `[materials_with_quantities]` | `[]` |
| Extract Equipment | `[equipment_with_parameters]` | `[]` |
| Extract All | `[full]` | `[]` |

Example for materials:

```yaml
extraction:
  presets: [materials_with_quantities]
  components: []
  fuzzy_enabled: false
```

Use one of the four presets for the first run. Add extra component names only when you intend the union described in section 5. Keep fuzzy matching off until you have inspected an exact run. `full` searches every component, including the large material catalogues, and is the long run.

### 7.5 Run the CLI

**Prerequisite.** Steps 7.2–7.4. No other process should be writing the HTML file or the snapshot.

**Working directory.** `C:\Users\User\batchlens-extract`

```powershell
poetry run python -m app.lexical_extraction --config $ConfigPath
```

The CLI has one argument, `--config`. There is no override flag, no preset flag, and no fuzzy flag.

**Expected.** The process stays in the foreground. Stdout ends with lines of this form:

```text
run_id=<uuid>
extraction_status=completed
component.materials=completed:<count>
component.units=completed:<count>
component.quantity_expressions=completed:<count>
publication_status=completed
peak_memory_bytes=<integer> method=windows_psapi_peak_working_set
manifest_path=<output>\<run_id>\manifest.json
exit_code=0
```

The component lines match the preset you selected. `$LASTEXITCODE` equals the printed `exit_code`. A new directory appears at `Join-Path $OutputDir <run_id>`.

Exit `0` means every requested component completed and the manifest was written. Exit `1` means a partial extraction was published. Exit `2` means extraction or pre-validation failed; a manifest exists only when the summary also prints `manifest_path` and `publication_status=completed`. Exit `3` means the manifest was not published, or configuration failed. Section 4.6 is the map.

**Duration.** A historical `full` run, fuzzy off, on an 18-page, 728-block reviewed HTML file, finished in 169.257 seconds, with a reported peak of 506,093,568 bytes. Treat that as a warning that `full` can take on the order of a few minutes on a similar document, not as a limit and not as proof of the later streaming-reader correction. A smaller preset is the appropriate first run. This guide did not time a new run.

### 7.6 Read the manifest and check hashes

**Prerequisite.** The CLI printed `manifest_path` and `publication_status=completed`.

**Working directory.** `C:\Users\User\batchlens-extract`

Copy the directory from the `manifest_path` line already printed. Do not start the CLI again.

```powershell
$RunDir = Split-Path -Parent "<paste the manifest_path value>"
$ManifestPath = Join-Path $RunDir "manifest.json"
Test-Path -LiteralPath $ManifestPath -PathType Leaf
```

**Expected.** `True`.

```powershell
poetry run python -c @"
from pathlib import Path
from app.lexical_extraction.publication import load_final_manifest, verify_artifact_hashes
p = Path(r'$ManifestPath')
manifest = load_final_manifest(p)
rows = verify_artifact_hashes(manifest, p.parent)
print('schema_version=' + manifest['schema_version'])
print('run_status=' + manifest['run_status'])
print('publication_status=' + manifest['publication']['status'])
print('html_sha256=' + manifest['validated_input']['html_sha256'])
print('snapshot_id=' + manifest['knowledge']['snapshot_id'])
print('database_sha256=' + manifest['knowledge']['database_sha256'])
print('configuration_sha256=' + manifest['provenance']['configuration_sha256'])
print('rules_sha256=' + manifest['provenance']['rules_sha256'])
print('fuzzy_requested=' + str(manifest['provenance']['fuzzy_requested']))
print('artifact_count=' + str(len(rows)))
for row in rows:
    print(row.component.value + ' ' + str(row.byte_size) + ' ' + row.sha256)
"@
```

**Expected.** `schema_version=batchlens.lexical-run-manifest.v1`. `publication_status=completed`. `run_status` matches the CLI `extraction_status`. `artifact_count` equals the number of completed components. The command raises if a listed file is missing or if its size or SHA-256 differs. `fuzzy_requested` is `False` when the YAML switch was off.

A completed manifest is a file-integrity record. It is not human approval of the findings and not pharmaceutical validation.

Optional byte check without parsing component JSON. PowerShell’s hash text is uppercase; the manifest digest is lowercase.

```powershell
$manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
$manifest.run_status
$manifest.extraction.components | Select-Object component, outcome, match_count
foreach ($item in $manifest.artifacts) {
    $full = Join-Path $RunDir ($item.relative_path -replace '/', '\')
    $hash = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
    "{0} size_ok={1} hash_ok={2}" -f $item.component, ((Get-Item -LiteralPath $full).Length -eq $item.byte_size), ($hash -eq $item.sha256)
}
```

**Expected.** One `size_ok=True hash_ok=True` line per artifact. Use `ConvertFrom-Json` on `manifest.json` only. Component artifacts are streamed by the publisher’s reader; this hash check does not need to parse them.

### 7.7 Stop, keep, and run again

The CLI does not resume. Ctrl+C stops the process. If that happens before finalize, no `manifest.json` claims completed publication. Leave the partial directory as it is.

To run again, keep the old `{run_id}` directory. Use the same output root if you want; the publisher creates a new UUID directory and refuses to replace an existing run directory. Change the YAML when you want a different HTML file or a different preset, then run step 7.5 again. Two runs are compared by `html_sha256`, `snapshot_id`, `database_sha256`, `rules_sha256`, and component match counts. `configuration_sha256` also includes absolute paths, so a different output directory changes that digest even when the selection is the same. `run_id` values differ every time.

If the summary has no `manifest_path`, publication did not finish. Do not rename staging files into `artifacts/` and do not write a manifest by hand.

## 8. Manual verification and troubleshooting

Perform these checks later, on a new run. This guide did not perform them.

| Check | Expected result |
|---|---|
| Validate HTML and snapshot without modifying them | Step 7.2 path checks pass, and a small preset reaches `publication_status=completed` with a `validated_input` and `knowledge` block. The HTML file and snapshot files keep the same hashes after the run. |
| Run a small preset | `unit_operations_with_steps`, `materials_with_quantities`, or `equipment_with_parameters`, fuzzy off. Manifest `run_status` is `completed` or, if nothing matched, still `completed` with count 0. |
| Run `full` | Only when you can leave the process for at least a few minutes. Historical evidence on an 18-page file was 169.257 seconds. Exit 0 and eight completed components are the success shape for that selection, not a required count of matches. |
| Check one span | In the component artifact, `block.text[start_char:end_char]` equals `matched_text` using Unicode code points. That confirms the locator. It does not confirm a manufacturing claim. |
| Zero-result versus failed | Summary `component.<name>=completed:0` and an artifact whose blocks have empty occurrences. A failure looks like `component.<name>=failed:<CODE>` and that component is absent from `artifacts`. |
| Partial publication versus failed publication | Exit 1, `run_status=partial`, `publication_status=completed`, manifest present, only completed components listed. Exit 3, no `manifest.json`. |
| Second run | A different `run_id`. Previous directory still present. Identities match when the HTML, snapshot, rules, and selection match. |

### Symptom map

| Symptom | Likely cause | Read-only check | Safe next action |
|---|---|---|---|
| `configuration_error=ConfigurationError`, exit 3, no run directory | Unknown key, bad enum, duplicate selection, non-integer limit, empty path, unsafe YAML, or `schema_version` other than integer 1 | Re-read the working YAML against section 3. Confirm you edited the copy, not the example | Fix the copy. Run again. |
| Argparse usage text, process status 2, no `extraction_status` | `--config` missing or an unsupported flag | The CLI help lists only `--config` | Re-run with `--config` and the working YAML path. |
| `cli_error=PublicationError`, exit 3, immediately | Output directory equals or lies inside the snapshot | Repeat the two containment tests in step 7.2 | Choose a new output directory outside the snapshot. |
| `extraction_status=pre_validation_failed` | HTML missing, unreadable, truncated, wrong version, duplicate attributes, or missing producer metadata | `Test-Path` the file. Search the start of the file for `data-review-html-version="1"` and the four producer attributes | Supply a reviewed HTML v1 export. Leave any empty run directory. Do not rename a PDF or a raw conversion HTML. |
| `error_code` contains `UNSUPPORTED_HTML_VERSION` or `MISSING_HTML_METADATA` | The file is not reviewed HTML contract `"1"`, or a producer attribute is absent or invalid | The root tag’s `data-review-html-version`, `data-job-id`, `data-review-revision-id`, `data-review-generation`, and `data-conversion-status` | Use the Stage 1 reviewed export. The engine will not infer approval from another file. |
| Snapshot error such as `WAL_PRESENT`, `MANIFEST_INVALID`, `REPORT_INVALID`, or `SCHEMA_MISMATCH`; exit 3; no manifest | Companion missing, snapshot incomplete, or a WAL/SHM/journal sidecar is present | Step 7.2 companion tests and the sidecar listing | Stop. Do not delete sidecars or edit the database. Point at a snapshot that already passes preflight. |
| `REPLAY_IDENTITY_CHANGED` or `SNAPSHOT_CHANGED` | The HTML or a snapshot companion changed while the run was reading | Compare the file’s SHA-256 with `validated_input.html_sha256` if a manifest exists. If no manifest exists, the pinned identity was not published | Keep files stable and start a new run. Do not merge the interrupted output with a later run. |
| `OVERSIZED_TERM` or another shard/buffer failure on one component | One term or one block exceeded a configured finite limit | `monitoring.resource_limits` in the manifest, when a manifest exists, and the component `error.code` | Keep the published partial run if exit is 1. Raise a limit only up to the maximum in section 3, in a new YAML and a new run. Do not edit the snapshot to shorten a term. |
| `run_status=partial`, exit 1 | One component failed after another completed. Dictionary components fail independently. The shared unit/value group fails its still-uncommitted members together | `extraction.components` and `errors` in the manifest | Use the completed artifacts. Investigate the failed code. Start a new run if you need the missing component. |
| No `manifest.json` | Publication failed, the process was stopped, or identities were not available | Directory listing of the `{run_id}` folder. Stdout `publication_status` and `publication_error` if the process returned | Leave the directory. Start a new run. Do not treat committed component files without a manifest as a finished publication. |
| `completed:0` and you expected hits | The selection did not include that component, fuzzy matching is off, the wording is not an eligible catalogue term, or a boundary rule rejected an embedded token | `provenance.resolved_components`, `fuzzy_requested`, and the block text around the expected phrase | A zero count means that full scan found no accepted hit. It does not mean the component was skipped. Changing presets requires a new run. A fuzzy neighbour, an alias, or a catalogue candidate is still not proof that the row is the right reading. |
| `completed:0` versus a missing summary line | Count 0 is a finished empty component. A missing line means that component was `not_requested` | The preset table in section 5 | Select the component and run again into a new directory. |

## 9. Handoff to the next capability

A finished Stage 2 run hands the later Extraction Review Workspace four kinds of evidence:

- immutable component artifacts, one per completed component, containing original block text and occurrences
- a final manifest that binds those files by relative path, byte size, and SHA-256
- the exact reviewed HTML identity (`html_sha256` and the producer attributes)
- snapshot, configuration, and rules identities (`snapshot_id`, database and manifest hashes, `configuration_sha256`, `rules_sha256`, fuzzy flag, engine and dependency versions)
- spans that locate each hit as Unicode code points in a named block

No Extraction Review Workspace is implemented in Stage 2. Nothing in this engine highlights spans in a browser, accepts an edit, or records human approval of a finding. The handoff stops at the published files.

A local Stage 2 run is complete when all of the following are true:

- the CLI process has returned
- `publication_status` is `completed` and `manifest_path` is present
- `load_final_manifest` accepts the file and `verify_artifact_hashes` agrees
- `validated_input`, `knowledge`, and `provenance` are present
- every requested component has an outcome, and each `completed` component has an artifact listed in the manifest

Those conditions mean the selected lexical scan finished and the files were sealed. They do not mean a person approved the mentions, that a batch was executed, that a material was charged, or that a parameter, a unit, and a value belong to one another. Counts, candidates, and fuzzy neighbours remain evidence for a later human review.

---

Source note. Inspection date 2026-09-29. Inspected commit `f4a9f97412e44c39434e9c39ba5be613d3d076fd` (2026-09-28, “lexical search L13”). Working tree at inspection: that commit, plus untracked `docs/BatchLens-Stage1-Overview-EN.md`, `docs/BatchLens-Stage1-Detailed-Local-Guide-EN.md`, `docs/BatchLens-Stage2-Lexical-Extraction-Overview-EN.md`, and `prompts/overview/`. No tracked file was modified. This guide is the new document.

Paths consulted: `src/app/lexical_extraction/` (`contracts.py`, `configuration.py`, `html_reader.py`, `knowledge_snapshot.py`, `field_mapping.py`, `comparison.py`, `dictionary_matcher.py`, `fuzzy_matching.py`, `dictionary_aggregation.py`, `unit_value_rules.py`, `unit_aggregation.py`, `value_expressions.py`, `parameter_unit_value.py`, `runner.py`, `monitoring.py`, `publication.py`, `__main__.py`), `examples/lexical_extraction/execution-config.example.yaml`, `pyproject.toml`, `poetry.lock` (Poetry 2.2.1; PyYAML 6.0.3, pyahocorasick 2.3.1, pydantic 2.12.5), `docs/FLAT_SQLITE_CONTRACT.md`, `docs/BatchLens-Stage2-Lexical-Extraction-Overview-EN.md`, `src/app/document_review/rendering.py` (producer attributes only), `.gitignore`, and the lexical sections of `.ai/03_common_handoff.md`, `.ai/01_implementation_roadmap.md`, `.ai/05_pipeline_contracts.md`, and `.ai/07_extraction_evaluation.md`. Tests under `tests/lexical_extraction/` were read for expected behaviour and were not executed.

Existence only, contents not opened and not re-hashed: the historical reviewed HTML under `.local-review-data\html-provenance-20260925\...`, the historical snapshot directory recorded in the handoff, `out\lexical-l13\...`, and a `.venv` directory were present. The section 7 commands, `poetry install`, and a new extraction run were not executed. The example YAML relative paths are not real inputs. The 169.257-second full run remains historical programmatic evidence and does not verify the later streaming-reader correction.

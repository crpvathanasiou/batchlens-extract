# BatchLens — L02: Execution Configuration and Preset Resolution

## 1. Authorization and stop boundary

L01 is user-accepted. Implement **L02 only**: strict, deterministic execution-configuration loading, fixed preset/component resolution, finite resource settings, effective-configuration provenance, a compact YAML example, focused tests, and the corresponding handoff/code-map documentation.

Stop after the L02 completion report. Do not implement HTML reading, SQLite access, source-field mapping, normalization, matching, value parsing, fuzzy calculation, aggregation, runner/CLI, monitoring, or artifact publication. This is one bounded Cursor task; it does not authorize L03 or later work.

## 2. Accepted baseline

Repository: `C:\Users\User\batchlens-extract`.

L01 in `src/app/lexical_extraction/contracts.py` is implemented and test-verified. It provides the fixed `Preset` and `Component` vocabularies, `RunProvenance` fields for requested presets/components and resolved components, `fuzzy_requested`, and `configuration_sha256`. The current handoff records 19 focused lexical-contract tests and a 289-test quality gate. Treat that as recorded baseline evidence; inspect the working tree and report your own actual results.

This task owns configuration loading and preset resolution only. The result is an effective, validated configuration that a later runner can consume. It must not cause file-system creation, HTML parsing, snapshot inspection, index construction, or extraction.

There is one deterministic extraction pipeline. The user may select presets and/or independently executable components, and set fuzzy matching enabled or disabled. Fuzzy defaults to disabled. Normalization, field selection, boundaries, matching methods, and value rules are fixed V1 implementation rules, not user-configurable options.

## 3. Read before editing

Read:

1. `AGENTS.md` and current `.ai/03_common_handoff.md`.
2. Relevant configuration, typing, Pydantic, determinism, testing, and documentation sections of `.ai/02_code_quality_standards.md`.
3. `.ai/00_project_reference.md`, `.ai/01_implementation_roadmap.md`, `.ai/04_code_map.md`, and `.ai/05_pipeline_contracts.md`.
4. `src/app/lexical_extraction/contracts.py` and `tests/lexical_extraction/test_contracts.py`.
5. `src/app/settings.py`, `src/app/document_jobs/settings.py`, and the canonical JSON hashing convention in `src/app/document_review/contracts.py`. Reuse small relevant conventions only; do not make lexical execution configuration depend on FastAPI environment settings or document-review modules.
6. `pyproject.toml`, `poetry.lock`, `pyrightconfig.json`, and `scripts/quality.ps1`.

The detailed technical handoff is supporting reference only if present locally. Its old configurable lexical-policy wording is superseded here: L02 must not create a policy file, profile selector, algorithm selector, field selector, stage list, LLM option, or generic plugin mechanism.

## 4. Permitted changes

Create:

- `src/app/lexical_extraction/configuration.py` — focused models and pure load/resolve/hash helpers.
- `tests/lexical_extraction/test_configuration.py` — public configuration behavior.
- `examples/lexical_extraction/execution-config.example.yaml` — valid synthetic configuration, containing paths only and no real document/snapshot content.

Update only when relevant:

- `src/app/lexical_extraction/__init__.py` — minimal public re-exports only if the repository convention warrants them.
- `pyproject.toml` and `poetry.lock` — add PyYAML as an explicit direct runtime dependency if it is not already declared directly. Do not make a broad dependency upgrade.
- `.ai/01_implementation_roadmap.md`, `.ai/03_common_handoff.md`, `.ai/04_code_map.md`, and `.ai/05_pipeline_contracts.md` — concise actual L02 state, configuration contract, example path, test evidence, and remaining limits.

Do not change `contracts.py` unless a concrete incompatibility with its existing public `Preset`/`Component` records is found; explain and stop before an unapproved redesign. Do not change existing application settings, APIs, renderer/review behavior, snapshot artifacts, source catalogues, or unrelated tests.

## 5. Required configuration contract

Use a safe YAML loader plus strict frozen Pydantic v2 boundary models. Parsed configuration must reject unknown fields and unsafe coercion. All configuration paths are declared in YAML as nonempty strings and are resolved against the configuration file's parent directory, never the shell working directory. Return resolved absolute `Path` values in the effective configuration. Do not require those paths to exist and do not create them in L02; later input/snapshot/output tasks own those preflight and publication checks.

Use one clear, versioned root shape equivalent to the following. Exact class/function names may differ, but preserve these meanings:

```yaml
schema_version: 1
input:
  reviewed_html_path: ./inputs/reviewed.html
knowledge:
  snapshot_directory: ./knowledge/flat-v1
output:
  directory: ./results
extraction:
  presets: [materials_with_quantities]
  components: []
  fuzzy_enabled: false
resources:
  sqlite_read_batch_rows: <finite integer>
  sqlite_cache_kib: <finite integer>
  max_terms_per_shard: <finite integer>
  max_term_codepoints_per_shard: <finite integer>
  result_buffer_records: <finite integer>
```

Required behavior:

- `schema_version` is exactly strict integer `1`.
- `input`, `knowledge`, `output`, `extraction`, and `resources` are required mappings. Unknown keys at every level are rejected.
- `presets` uses exactly the seven locked values: `unit_operations`, `unit_operations_with_steps`, `materials`, `materials_with_quantities`, `equipment`, `equipment_with_parameters`, `full`.
- `components` uses exactly the eight locked values: `unit_operations`, `process_steps`, `materials`, `equipment`, `parameter_names`, `units`, `quantity_expressions`, `parameter_value_expressions`.
- At least one preset or component is required. Duplicates within each requested list are invalid because they make requested selection ambiguous. A preset and an independently requested component may overlap; that is a valid combined request.
- `fuzzy_enabled` is a strict Boolean and defaults to `false` only when `extraction` omits it. It is the sole matching switch exposed by this configuration.
- Resource fields have documented finite defaults plus strict positive integer validation and sensible explicit upper bounds. They are safeguards, not a claimed memory or performance guarantee. Do not expose CSV, schema-rebuild, source-field, policy, normalization, boundary, Aho–Corasick algorithm, or per-method settings.

## 6. Fixed preset resolution

Implement a pure resolver that takes requested presets and requested components, returns the deterministic union of `Component`, and performs no I/O. Preserve the original request separately in the effective configuration; do not replace it with only the union.

Use this exact V1 mapping:

| Preset | Resolved components |
|---|---|
| `unit_operations` | `unit_operations` |
| `unit_operations_with_steps` | `unit_operations`, `process_steps` |
| `materials` | `materials` |
| `materials_with_quantities` | `materials`, `quantity_expressions`, `units` |
| `equipment` | `equipment` |
| `equipment_with_parameters` | `equipment`, `parameter_names`, `parameter_value_expressions`, `units` |
| `full` | all eight components |

Return resolved components in one documented canonical order: `unit_operations`, `process_steps`, `materials`, `equipment`, `parameter_names`, `units`, `quantity_expressions`, `parameter_value_expressions`. Selection order must not alter the resolved union or effective configuration digest.

`with` means co-execution only. Resolution must not create a Unit Operation/material/equipment/parameter association, require a child value, or duplicate a shared component. `full` does not enable fuzzy matching and does not activate LLM/RAG/embeddings.

## 7. YAML safety, overrides, and provenance

Provide one public loader accepting a configuration-file path and, if useful, a small typed per-run override object. Do not add a CLI.

- Read YAML with a `SafeLoader`-based implementation that rejects duplicate mapping keys, non-mapping roots, non-string keys, merge keys, anchors/aliases, unsafe tags/constructors, and multiple YAML documents. Reject empty documents.
- A documented per-run selection override may replace the YAML `presets` list and/or `components` list; it never appends implicitly. A fuzzy override may replace the Boolean. Apply overrides before fixed-union resolution. Keep overrides typed; they are a future caller boundary, not environment-variable settings.
- Apply resource defaults before validation/serialization. Resolve all relative paths before calculating provenance.
- Provide a pure canonical SHA-256 helper for the effective configuration. It serializes the effective configuration content deterministically using UTF-8 canonical JSON (`sort_keys=True`, compact separators, `ensure_ascii=False`, `allow_nan=False`). Its output is lower-case 64-character hexadecimal and is suitable for the existing `RunProvenance.configuration_sha256` field.
- Two semantically equal selections with different YAML list ordering must produce identical resolved components and identical effective configuration digest. The preserved requested list may retain user order in its own record; its ordering must not make the effective operational provenance unstable. Document this intentional distinction.
- No paths, policy-file references, or application environment values alone constitute effective provenance; the effective resolved content and digest do.

## 8. Required tests and example

Add meaningful focused tests for:

1. The checked-in YAML example loads and produces absolute paths, defaults, a valid digest, and the expected resolved component union.
2. Every preset maps exactly as in section 6; component-only execution; overlapping preset/component requests; combined presets; `full`; no duplicate resolved components; canonical resolved ordering independent of input selection order.
3. `with` presets do not encode associations or require child values. This can be established by checking only component resolution and absence of association fields; do not construct an extractor.
4. Default fuzzy `false`, explicit `true`, strict rejection of strings/numbers, and no other matching/algorithm configuration fields accepted.
5. Missing/unknown/nested-unknown fields; unsupported schema versions; empty selection; duplicate presets/components; invalid enum; nonpositive/out-of-range/coerced resource values; empty path values.
6. Duplicate YAML key, non-mapping root, multiple documents, merge key, anchor/alias, unsafe constructor/tag, and non-string mapping key rejection.
7. Relative paths are based on the config file directory, not the process CWD. The loader neither requires referenced paths to exist nor creates directories.
8. Typed override replacement semantics and resulting union/digest. Verify configuration digest stability for semantically equal operational selections and change when an effective value changes.
9. JSON-safe serialization/round trip of the effective configuration and direct compatibility of its resolved preset/component/fuzzy/digest values with the existing `RunProvenance` fields. Do not change L01 contracts to accommodate this.

Keep fixtures synthetic and local temporary files only. Do not use the large SQLite, production paths, original CSVs, reviewed HTML, network, or Docker.

## 9. Documentation, verification, and Definition of Done

Document the final root YAML shape, fixed preset map, only user-facing `fuzzy_enabled` switch, resource meanings/defaults/bounds, relative-path rule, override replacement behavior, and effective-configuration SHA-256. State that snapshot compatibility, HTML validation, parsing, matching, monitoring, runner, and publication remain unimplemented.

Run the focused configuration tests and the applicable repository gate using the supported local environment (`scripts/quality.ps1` where appropriate). Do not weaken gates, edit unrelated files, or target historical test counts. Report actual commands, counts, and any environment limitation precisely.

L02 is complete only when a later caller can load strict YAML into a deterministic effective configuration, resolve valid selections to the exact fixed component union, obtain reproducible effective provenance, and receive useful validation failures without starting extraction or touching input/snapshot/output artifacts.

Manual extraction acceptance is not applicable to L02 because no reader or matcher exists yet.

## 10. Completion report and stop

Return:

1. Exact changed files and concise purpose of each.
2. Public configuration models/functions and their input/output invariants.
3. Final YAML example and the fixed preset-to-component mapping.
4. YAML safety behavior, path/override semantics, default resource values/bounds, and effective-digest rule.
5. Actual test/gate commands and results, including any failure or environment block.
6. Documentation updates and explicit remaining limitations.

**Stop after L02. Await review and explicit user acceptance. Do not implement L03 or prepare later implementation prompts.**

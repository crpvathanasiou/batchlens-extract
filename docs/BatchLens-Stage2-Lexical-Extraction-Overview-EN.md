# BatchLens — Stage 2: Lexical Extraction Engine

## 1. Purpose and boundaries

Stage 2 finds catalogue mentions in reviewed HTML and keeps each hit tied to the exact text where it occurred. It starts from a reviewed HTML file supplied to it and from a pinned, read-only catalogue snapshot. It ends when the selected searches have a recorded outcome and, if publication succeeds, a new run directory holds the evidence files and a final manifest.

The search is deterministic. The same reviewed file, snapshot, and selection produce the same matches. A match shows that a catalogue spelling, alias, code, or controlled value form was found. It is not a pharmaceutical truth claim, not proof that a batch was executed, and not a decision that two mentions belong together. It does not infer associations, build a graph, or retrieve meaning with vectors or a language model.

## 2. Inputs and safe preparation

The document input is one reviewed HTML file in contract version 1. The engine validates that structure and the producer markers for the version, the job, the review revision, the review generation, and the conversion status. It does not query a document-review store, so those markers and the file hash do not prove a current human approval. Operationally, Stage 1 approval and, later, membership in the Approved Documents folder decide which file is supplied. The engine reads that file to the end and records a SHA-256 hash of the exact bytes it read. That hash exists only after a complete read and identifies those HTML bytes, not the canonical reviewed JSON.

The knowledge input is one flat SQLite snapshot: a prepared copy of four catalogue tables for materials from two sources, equipment, and unit operations. Before any search, the engine checks the snapshot’s identity, companions, and integrity, and opens the database read-only. It does not import the original CSV files, normalize the tables, rebuild the catalogue, or write to the snapshot. A later change stops the read under that checked identity.

## 3. The extraction workflow, step by step

1. **Validate the document and the snapshot.** The engine checks reviewed HTML version 1 and the producer markers, without proving current human approval, and it prefights the snapshot. The execution file supplies paths and finite resource limits, not matching rules. Work continues only when both inputs validate.

2. **Choose eligible catalogue terms.** Fixed field rules turn source rows into search terms for the selected components only. Each term keeps its original spelling, source table, field, and row identity. Blank cells yield no term. Names, aliases, codes, and process steps stay separate, and a generic cue does not gain an invented operation identity.

3. **Find matches inside fixed bounds.** Comparison uses fixed exact and normalization-aware rules, and fixed boundaries so a code or a unit is not extended into neighboring characters. Terms are handled in bounded shards, and the document text is not rewritten. If the HTML file changes between passes, the run fails rather than mixing two documents.

4. **Keep repetitions, overlaps, and ambiguity.** Every accepted hit stays. Repeated spellings, overlapping spans, and more than one catalogue candidate for the same span are retained, with further source rows kept as supporting references. Ambiguity is kept rather than reduced to one winner.

5. **Add independent parameter, unit, and value evidence when selected.** Parameter names use the dictionary path. Units and values use separate fixed rules. Units follow fixed V1 exact and normalization-aware token and boundary rules and are never fuzzy-matched.

6. **Record outcomes and publish.** Each selected component receives one outcome and a monitoring record. Publication writes one artifact per completed component, then a final manifest only if publication itself completes. Output inside the snapshot directory is refused.

## 4. What can be selected, and what matching means

The user chooses named presets and may add components directly. Presets may be combined. The engine runs their union in a fixed component order. The word `with` means those components run together. It does not mean a relationship was inferred.

| Preset | Requested components |
|---|---|
| `unit_operations` | Unit operations only |
| `unit_operations_with_steps` | Unit operations and process steps |
| `materials` | Materials only |
| `materials_with_quantities` | Materials, quantity expressions and units |
| `equipment` | Equipment only |
| `equipment_with_parameters` | Equipment, parameter names, parameter-value expressions and units |
| `full` | All V1 components |

Fuzzy matching is the only other extraction switch, and it is off unless explicitly enabled. The user cannot choose the algorithm, the normalization profile, which catalogue columns are searched, or a per-field switch. Resource limits bound the run. They do not alter matching.

Ordinary matching is exact, or exact after the fixed comparison normalization. Fuzzy matching, when enabled, applies only to one alphabetic natural-language word of at least six characters, at an edit distance of one, and only for eligible equipment types, parameter names, unit operations, and process steps. It never applies to materials or chemicals, UNII or other codes, generic cues, abbreviations, phrases, or units. Units instead use fixed V1 exact and normalization-aware token and boundary rules, including case-only controlled-vocabulary forms where specified, with no fuzzy matching. A unit by itself does not identify equipment, a parameter, or an operation.

## 5. Evidence, results, and traceability

A dictionary occurrence keeps the original literal span, the page, the block, and the node, as a half-open range of Unicode code points in that block’s text. The recorded text must equal that slice. It also keeps the matching method — exact, normalization-aware exact, or fuzzy — the catalogue candidates and source rows, catalogue identifiers when present, and a qualification when the catalogue says more context is required. Alternative candidates and supporting rows stay visible for later review.

Parameter names are dictionary occurrences. Unit and value occurrences keep their own fixed recognition and validation provenance. They do not necessarily carry dictionary candidates or an exact, normalization-aware, or fuzzy matching-method field. In `Impeller speed: 120 rpm`, a selected run may record “Impeller speed” as a parameter-name mention, “120 rpm” as a value expression, and “rpm” as a unit. Those records do not assert that the speed belongs to a particular impeller, or that the number was an executed measurement. Catalogue equipment scope on a parameter row is not a detected equipment mention, and an ambiguous number is not replaced by a guessed decimal.

Spans can support later highlighting, but no review workspace for these findings exists yet.

## 6. Outcomes, publication, and observability

A finished component is `completed`, including a count of zero when nothing matched. Zero is an empty result, not a failure. `failed` means the component did not finish and carries a structured error. `partial` means usable results remain but coverage is incomplete. The run is `completed` when every requested component completes, `failed` when every requested component fails, and `partial` when some complete and others do not. Completed counts inside a partial run stay usable.

Publication is separate. A new run directory receives `artifacts/component-<name>.json` for each completed component. `manifest.json` is written last, and only when publication completes. A partial extraction may still be published: the manifest lists the completed files and states the partial outcome. A failed or interrupted publication does not claim a final manifest. The manifest records input, snapshot, configuration, and rules identities, outcomes, monitoring, and each artifact’s hash and size.

The engine is invoked through a callable run boundary or a command-line entry that reads an execution file.

One historical `full` run, with fuzzy off, used an 18-page, 728-block reviewed HTML file. It finished in 169.257 seconds, with a reported peak of 506,093,568 bytes. That figure is historical programmatic evidence. It is not pharmaceutical validation, it was not rerun for this document, and it does not verify later publisher corrections.

## 7. Current completion boundary and next handoff

Stage 2, as implemented, can validate reviewed HTML version 1 structure and producer provenance, run the selected lexical components against the pinned read-only snapshot, and publish provenance-preserving artifacts. L01 through L13 are implemented, covered by recorded quality gates, and user-accepted.

Stage 2 does not provide a workspace to review or approve these findings, an edit workflow for them, large-language-model or vector extraction, a graph, or logic that links a material to a quantity, a parameter to equipment, or a step to an operation.

---

Source note. Inspected commit `f4a9f97412e44c39434e9c39ba5be613d3d076fd` (2026-09-28, “lexical search L13”). Untracked `docs/BatchLens-Stage1-Overview-EN.md` and `prompts/overview/` were already present; no tracked files were modified before this document. Behavior was taken from the implementation and from recorded handoff and evaluation evidence. Tests were read as expected behavior and were not executed for this task. Principal files: `src/app/lexical_extraction/contracts.py`, `src/app/lexical_extraction/configuration.py`, `src/app/lexical_extraction/html_reader.py`, `src/app/lexical_extraction/knowledge_snapshot.py`, `src/app/lexical_extraction/runner.py`, `src/app/lexical_extraction/publication.py`, `.ai/05_pipeline_contracts.md`, `.ai/07_extraction_evaluation.md`, `docs/FLAT_SQLITE_CONTRACT.md`.

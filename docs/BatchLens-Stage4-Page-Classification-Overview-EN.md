# BatchLens — Stage 4: Page Classification and Extraction Routing

## 1. Purpose and boundaries

Stage 4 classifies every page of one eligible Stage 1 approved/reviewed HTML v1 document so later lexical extraction can skip pages that are conservatively identified as non-extractable supporting content. It starts from that reviewed HTML and its existing reviewed-document/page provenance. It ends when the local workspace has a terminal classification outcome for that HTML identity, and optionally when **Extract All** has submitted a Stage 2 run on the resulting eligible pages only.

Stage 4 classifies pages. It does not convert PDFs, change the reviewed HTML bytes, alter Stage 1 approval, or create a separate PDF/page identity. It does not extract entities, build a graph, infer material/equipment/process associations, or use vector/RAG retrieval. Stage 2 remains the independent deterministic Lexical Extraction Engine. Stage 3 remains the only human extraction-result review/approval scope; the single final action **Approve extraction result** is unchanged.

The current implementation is a local MVP slice under `src/app/page_classification/`, the extraction-review Stage 4 adapter, local harness routes, and the Vue extraction-review workspace. It is implemented and covered by focused automated tests. A recorded local end-to-end acceptance used a real configured OpenAI classification and a classified Stage 2 extraction on the local harness. It is not a production-mounted or authenticated workflow, and live model quality is not guaranteed by deterministic tests.

## 2. Inputs, three calls, and validation

The canonical input is one Stage 1 reviewed HTML v1 file and its existing producer provenance (`job_id`, review revision, generation, conversion status, and the SHA-256 of the HTML bytes after a complete read). The document is prepared once; each page keeps its existing page number and page HTML id. The classifier receives the full-page HTML fragment for that page, not a rewritten or truncated summary.

For every page, Stage 4 runs three fixed, independent structured classification calls, each with a locked prompt and a Pydantic response contract:

| Call | Group | Role |
|---|---|---|
| 1 | Materials and equipment | Labels for bill-of-materials and equipment-list content |
| 2 | Process, operations, and controls | Labels for manufacturing, execution, controls, packaging, and related operational content |
| 3 | Document and supporting records | Labels for covers, TOC, signatures, acknowledgements, disposition, change history, and other supporting record types |

Returned labels must come only from each call’s locked allowed set. Exactly one evidence item is required for each returned label. Quote and reason are each limited to 1–240 characters. Labels and evidence are order-independent for validity, but the lists retain the order received. Evidence is associated by its own `label` field, not by list position. Empty label lists are allowed when a call reports that status appropriately.

`OTHER_UNCLASSIFIED` is application-generated only. The model cannot return it. The application assigns it when all three calls are structurally valid with status `ok` and the merged label union is empty; that page then requires review and remains eligible for extraction.

Source-aware validation proves location, not semantic correctness of the classifier’s label. It uses only one HTML-entity decode and whitespace collapsing on page text, element text, and quotes. Readable source excludes scripts, styles, and comments. Supported exact identifier values come from `id`, `data-node-id`, `data-element-id`, or `data-table-id` on the current page only. Validation is page-local. When the same identifier appears on exactly two elements that are an `article.element` wrapper and its direct content child, the article wrapper is used; other multi-matches are ambiguous. Missing or ambiguous identifiers, or a quote outside the resolved target, preserve the label and evidence but mark that item unverified and require review.

## 3. Classification outcome and conservative extraction routing

Four concerns stay distinct:

1. **Classification call/result status** — whether the three calls completed, failed, were invalid/incomplete, or produced a merged page kind such as `completed`, `empty`, `incomplete`, or `needs_review`.
2. **Page eligibility/exclusion** — whether Stage 2 may scan that page under the conservative policy.
3. **Stage 2 processing/publication status** — whether the lexical engine completed, partially completed, or failed for the selected pages.
4. **Stage 3 extraction-result approval** — whether a person approved the committed current review for one lexical run.

A page is excluded from lexical extraction only when every final label belongs to the fixed exclusion set, and only under a fully valid, non-empty, exclusively excluded-label condition with no incomplete, failed, invalid, conflicting, `needs_review`, or unverified-source-evidence state. The implemented exclusion labels are:

```text
NON_RELATED
COVER_PAGE
TABLE_OF_CONTENTS
DOCUMENTATION_INSTRUCTIONS
REFERENCE_DOCUMENTATION
SIGNATURE_LOG
SIGNATURE_APPROVAL
ACKNOWLEDGEMENT
BATCH_REVIEW_DISPOSITION
DOCUMENT_CHANGE_HISTORY
```

Every other page remains eligible. Incomplete, failed, interrupted, empty, fallback `OTHER_UNCLASSIFIED`, mixed, `needs_review`, or source-unverified pages remain eligible. Pages not yet reached before a failed or interrupted classification also remain eligible.

**Extract All** uses the existing Stage 2 `full` action on the selected eligible pages only. When no page restriction is supplied, Stage 2 behavior is unchanged. The reviewed HTML bytes and existing page identities remain unchanged. Stage 2 provenance/manifest records that Stage 4 restricted the scan; Stage 2 does not create synthetic records for skipped pages.

If every page is excluded, the outcome is completed and informational: the workspace reports that no pages are eligible, and no empty Stage 2 job is submitted.

## 4. Local user journey

The implemented local MVP journey is:

1. Select an eligible approved/reviewed document from the Approved Documents root.
2. Start **Classify pages**.
3. View truthful classification progress or a terminal outcome (`completed`, `failed`, or `interrupted`).
4. Inspect approved HTML on the left and, on the right, page labels, evidence, source-validation state, and the eligible/excluded decision.
5. Select **Extract All** when the classification state is terminal and the workspace allows it.
6. Inspect lexical progress/outcome separately from classification.
7. When the resulting classified run is reviewable, inspect immutable classification context and lexical findings together.

Classification information is read-only and informational. There is no classifier label editing, classifier approval, page-level approval, retry UI, or separate classifier-management screen. Incomplete, failed, interrupted, invalid, conflicting, or `needs_review` classification remains visible and does not create a manual-resolution workflow.

Existing By page / All findings, Add / Edit / Remove / Restore, Save, Download TXT, and **Approve extraction result** retain their Stage 3 meaning. A separate **Download classifications TXT** export may also be available; it is distinct from the Stage 3 extraction-results TXT download.

## 5. Persistence, run binding, diagnostics, and restart truthfulness

Local persistence keeps one current classification state per reviewed-HTML identity:

```text
<data-dir>/page-classifications/<sha256(reviewed-html-binding)>/current-classification.json
```

That state binds source provenance and the HTML-byte SHA-256, and records per-page merged results, evidence/validation state, eligibility, status/progress, and timestamps. There is no classifier revision history, approval ledger, retry ledger, generic workflow engine, or SQLite classification store.

Interrupted in-progress work is represented truthfully after restart as `interrupted`, with completed page results retained and no automatic rerun. Within one local application process, one active classifier worker is allowed per data directory. This is not a cross-process locking or queue platform.

When **Extract All** submits a classified lexical job, an immutable classification snapshot is stored beside that job as the exact input context used by the run. Later reclassification of the current document does not rewrite that snapshot. It is not a generic classification-history feature.

Bounded local diagnostic bundles live under:

```text
<data-dir>/page-classification-diagnostics/<classification-run-id>/
```

At a high level each bundle contains a manifest, copied prompt/schema assets, per-page request records, response or error records, and the merged page result. The manifest records non-secret effective model settings. For structured-output parse failures on future runs, diagnostic details needed for troubleshooting may also be retained. Retention keeps the newest valid bundles (currently five). These artifacts are local troubleshooting material and may include document content, so they must be handled accordingly. Raw failed provider content is available only for runs that include the diagnostic correction; older historical failure records must not be assumed to contain it.

## 6. Approval and non-goals

Stage 1 source-document approval is separate from Stage 4 classification. Stage 4 does not approve a source document or an extraction result.

Stage 3 has one final action only: **Approve extraction result**. That approval applies only to the committed current extraction-review content for its lexical run. Classification labels are informational. They never replace lexical findings or alter the meaning of that approval.

Deferred or outside this local MVP:

- production API mounting and authentication;
- classifier label editing, classifier approval, or classification history;
- LLM entity extraction;
- graph, association, or recipe-assembly logic;
- broader audit/history infrastructure;
- generic queues or workflow engines;
- SQLite review/classification stores;
- automatic approvals;
- any claim that live model behavior or pharmaceutical classification quality is guaranteed by contract tests.

## 7. Current completion boundary and evidence

Stage 4 page classification and conservative extraction routing are **implemented** in this repository and **test-verified** by focused suites under `tests/page_classification/`, Stage 4-related `tests/extraction_review/`, and Stage 2 page-restriction coverage in `tests/lexical_extraction/`.

A recorded local harness end-to-end acceptance used a real configured OpenAI classification of an approved reviewed HTML document and a subsequent classified **Extract All** path, including inspection of classification context with lexical findings and ordinary Stage 3 save/approve behavior on a reviewable run. That evidence supports the local MVP journey described above. It does not prove production mounting, authentication, AWS integration, or classification accuracy for arbitrary documents.

Live model behavior and classification quality remain **unverified** as product guarantees: deterministic tests use fakes/fixtures and do not establish pharmaceutical correctness of returned labels.

---

Source note. Behavior was taken from the current Stage 4 implementation and focused tests, and from recorded local acceptance of the Stage 4 MVP on the extraction-review harness. Principal areas: `src/app/page_classification/` (`contracts.py`, `page_input.py`, `page_classification_schemas.py`, `rules.py`, `runner.py`, `service.py`, `store.py`, `diagnostics.py`, `prompts/`, `json_schemas/`), `src/app/extraction_review/stage4_local.py`, `src/app/extraction_review/local_jobs.py`, `src/app/api/extraction_reviews.py`, `src/app/lexical_extraction/runner.py` and `contracts.py`, `frontend/src/components/ExtractionReviewWorkspace.vue`, `frontend/src/extractionReview.ts`, and the focused Stage 4 test directories named above. Tests and live classification were not executed for this documentation task.

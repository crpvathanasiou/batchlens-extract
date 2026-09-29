# BatchLens — Stage 1: PDF Conversion, Human Review, and Approval

## 1. Purpose and boundaries

BatchLens Extract prepares pharmaceutical manufacturing PDFs so a person can correct and approve recognized content before any later extraction of materials, equipment, operations, or parameters. Stage 1 starts when a PDF is accepted for conversion and ends when one revision is approved and its reviewed HTML and JSON have been written.

Conversion keeps recognized text and tables tied to the source PDF. The reviewer corrects that text and decides each conversion warning. This stage does not extract recipe facts. Document-review approval is not batch release, regulatory approval, or a 21 CFR Part 11 electronic signature, and it leaves the original conversion files unchanged.

## 2. Input and conversion

The input is a PDF. On the application path, an authenticated owner uploads a file whose name ends in `.pdf`. A worker sends it to Amazon Textract for text and layout recognition, and Amazon Textractor 1.10.0 builds the review files. No other recognition engine is on this path.

`document.json` is the canonical document: physical pages, reading order, text, tables, selection states, links to recognized blocks, and warnings. `textract.json` is the raw result. `document.html`, plus one HTML file per page, is an unreviewed reading view. The reviewer edits a projection of the canonical document. A save updates that document and does not rewrite the original HTML.

The job finishes as `SUCCEEDED` or `PARTIAL_SUCCESS`. Partial success means recognition was incomplete, and missing text is not invented. `POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY` may flag a plain plus that might be a plus-minus, without changing characters. Figures are warnings, not pictures in the HTML, and the result is not a visual copy of the PDF.

Review can open only after one of those job statuses, and only when the canonical document and raw result are both present. The local review harness does not run recognition. It opens a supplied PDF together with those three files.

## 3. The user journey, step by step

1. **Convert the PDF.** The system stores the PDF and writes the conversion files described above. The user waits until the job is `SUCCEEDED` or `PARTIAL_SUCCESS`.

2. **Open the workspace.** The source PDF is shown beside the same page of converted text, with navigation and zoom. Before the first persisted review action, the review status is `NOT_REVIEWED`; the original conversion artifacts already exist. A mismatch between the declared page count, converted pages, and raw recognition pages blocks final approval and export.

3. **Correct text and decide findings.** The user edits text only. Table identity, dimensions, and source links remain fixed. Findings represent conversion warnings and are initially filtered to the current page; the user can choose to view all warnings. The user may apply a suggested plus-minus replacement, keep the original, acknowledge a limitation, or mark a finding resolved after editing its text. These changes and decisions remain in the draft until saved.

4. **Save the draft.** A newly committed Save draft action stores an immutable revision, records `DRAFT_SAVED`, and sets the review status to `IN_REVIEW`. Unsaved editor changes are not durable. The saved draft remains available after reload and after restarting the local harness with the same data directory. Recovery of a submitted but unconfirmed save is handled separately, as described below.

5. **Approve the current page.** Approve page records approval for that page only, provided every finding on it has a current decision. Other pages remain unchanged. Page approval does not approve the whole document or create export files.

6. **Approve the document and create the exports.** Approve & Export requires a complete, consistent page set, every page approved against its current text, and every finding decided. The server creates a new approved revision, writes its reviewed HTML and JSON, and sets the review status to `APPROVED`. The user downloads each file separately.

## 4. What approval means

A page approval is bound to a hash of that page’s text. Saving a later text edit removes approval from the affected page and clears document approval. Pages whose text has not changed retain their approval. A finding decision is bound to the text in its evidence region; changing that region makes the finding unresolved until a new decision is recorded.

Final approval creates a separate revision with the action `DOCUMENT_APPROVED`. Conversion status remains separate from review status: a conversion job does not become “approved.” An incomplete or inconsistent page set cannot receive final approval or produce a new approved export pair.

Approval applies to the reviewed document revision. It does not constitute manufacturing batch release, regulatory approval, or validation of downstream extraction.

## 5. Saving and traceability

Each newly committed save, page approval, or document approval creates an immutable revision containing the reviewer identity and server timestamp. A head record identifies the latest revision, while earlier committed revisions remain reachable.

Retrying a committed save with the same operation ID and matching request fingerprint does not create another revision. Reusing that operation ID with different request content is rejected. Other updates based on an outdated revision are rejected as conflicts rather than silently overwriting newer work.

The same browser tab can recover a submitted but unconfirmed save after reload while its pending-save record remains available in session storage. This mechanism does not persist arbitrary unsaved editor changes and should not be relied upon across tabs, after closing the session, or after clearing storage.

The committed revisions provide a history of who saved or approved which version, including approvals subsequently invalidated by edits. In the local harness, a derived `history.jsonl` is rebuilt from that history after a successful publish. The review screen does not depend on this file, and the file is not the authoritative review record. This traceability mechanism does not by itself establish a complete regulatory audit trail or electronic-signature system.

## 6. Outputs and handoff

| Artifact | Role |
|---|---|
| Source PDF | Unchanged input, shown beside the review. |
| `textract.json`, `document.json`, `document.html`, per-page HTML | Original conversion outputs. They stay unreviewed. |
| Review revisions | Drafts, page approvals, and the approved revision. Reviewed text is the canonical document in the revision. |
| Reviewed HTML and reviewed JSON | Created together by Approve & Export. Only the HTML is the next stage’s input. |

The JSON download is the approved envelope: corrected document, page approvals, and document approval. The HTML is a separate rendering of that revision, with a visible approval line and markers for contract version `1`, job id, review revision id, generation, conversion status, and node and source-block identifiers. The markers name the rendered revision. They do not prove approval by themselves, and the JSON does not point at the HTML bytes.

The next stage reads only that reviewed HTML. It requires version `1` and those identity fields, and it records a SHA-256 of the file only after reading it to the end. The hash is of the bytes consumed, not a value taken from the JSON. Term matching is outside Stage 1.

## 7. Current completion boundary

Stage 1 is finished for the user when Approve & Export has succeeded and both downloads are available. Review status is `APPROVED`. A further saved edit returns the document to `IN_REVIEW`. The edited page must be approved again, and Approve & Export must be repeated, before a new export pair exists.

The workflow is implemented. A person has confirmed, on the local harness, side-by-side review, editing, save and reload, findings, page approval, loss of approval after a later edit, blocked export while work remains, and downloads that contain the correction. Same-tab recovery after a lost response was accepted on a separate local run. The harness is the real review application with a test identity and disk files, and it does not call Textract.

Upload, Textract, and cloud storage are implemented and not live-verified. The feature is off unless enabled. HTML markers are covered by automated tests, with no recorded manual browser check. Local history rebuild is test-verified, with no recorded manual acceptance, and there is no production history screen.

---

Source note. Inspected commit `f4a9f97412e44c39434e9c39ba5be613d3d076fd` (2026-09-28, “lexical search L13”). Untracked `prompts/overview/` was present; no tracked files were modified before this document. Behavior was taken from the implementation and recorded handoff evidence. Tests were read as expected behavior and were not executed for this task. Principal files: `src/app/document_jobs/service.py`, `src/app/document_conversion/adapter.py`, `src/app/document_review/service.py`, `src/app/document_review/rendering.py`, `frontend/src/components/ReviewWorkspace.vue`, `frontend/src/components/FindingsPanel.vue`, `src/app/lexical_extraction/html_reader.py`, `.ai/03_common_handoff.md`.

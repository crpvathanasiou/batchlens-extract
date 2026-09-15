# 03 — Common Handoff

## 1. Current state — 2026-09-15

**Conversion-warning visibility implemented and locally verified; ready for review.**
The immediate focus remains the document-conversion vertical slice:
PDF upload → AWS Textract → structured document + HTML → download.

Work started from the supplied current `batchlens-extract.zip`. Conversion was already
integrated; `INTEGRATION.patch` was not reapplied. No commit, push, deployment, AWS
resource creation or real PDF processing was performed.

Historical HEAD supplied by the previous handoff: `f5b3eba44ea8d08e96ab78354668fc1bbc6f4f57`
on `master`. This ZIP has no Git metadata, so publication state was not reverified.

## 2. Warning visibility now implemented

- Existing `Document.status` and `Document.warnings` remain the source of truth.
- Full-document HTML shows PARTIAL_SUCCESS prominently and lists every warning,
  including warnings on SUCCEEDED documents and references to unavailable pages.
- Each warning displays its code, available page numbers and plain block references.
  Unknown codes remain visible; all dynamic warning values are HTML-escaped.
- Individual page downloads retain the document's partial status. They include warnings
  explicitly assigned to that page and unassigned warnings labeled as document-level.
  Multi-page references are retained. Sequential and process-pool output remain identical.
- No-warning output makes no accuracy, verification or human-approval claims.
- `Job.warning_count` and `JobStatus.warning_count` default to zero for older records.
  Completion persists `len(document.warnings)`; existing status/list routes expose it
  without reading S3 artifacts or duplicating warning details in job metadata.
- The UI uses safe text construction for a partial-result label and completed-job
  warning counts, including SUCCEEDED jobs, with details directed to downloaded HTML.
  Upload, polling, retry and download controls remain in the existing flow.
- Historical artifacts/counts are not backfilled. Older jobs without this metadata
  load with zero; that default is not an assertion that their conversions had no warnings.

Generated HTML remains script-free. Existing CSP, authentication, ownership, source
anchors, table projection and numeric page ordering are preserved.

## 3. Preserved capacity baseline

The capacity correction was accepted in the task brief. `process_claimed()` still
initializes `prior_uncertain = job.unknown_submission` before its try block, deadline
checks and initial heartbeat. The pre-submission uncertainty mark, definitive rejection
handling, slot reacquisition, generation-scoped releases, interrupted cleanup recovery,
source version pinning and request tokens are unchanged.

The entire `service.py` diff is one additional completion metadata entry:
`"warning_count": len(document.warnings)`.
Existing crash-after-accept, stale cleanup, deadline-after-crash and prior-uncertainty
heartbeat regressions remain passing. No lifecycle redesign or normalization changes.

## 4. Exact changed files

- `src/app/document_conversion/html.py`
- `src/app/document_conversion/README.md`
- `src/app/document_jobs/contracts.py`
- `src/app/document_jobs/service.py`
- `src/app/document_jobs/static/app.js`
- `src/app/document_jobs/static/style.css`
- `tests/document_conversion/test_converter.py`
- `tests/document_conversion/test_jobs.py`
- `.ai/03_common_handoff.md`

No API route or index.html changes were needed. Dependencies, infrastructure, LLM
wrapper and extraction/audit/editor modules were not modified.

## 5. Actual verification

A fresh Python 3.11.16 virtual environment was installed from the unchanged Poetry lock.
The repository root was used for all commands.

| Command / check | Actual result |
|---|---|
| `poetry install --no-interaction` | Passed; installed existing locked dependencies |
| `poetry run ruff check .` | All checks passed |
| `poetry run ruff format --check .` | 42 files already formatted |
| `poetry run pyright` | 0 errors, 0 warnings, 0 informations |
| `poetry run pytest` (in inherited environment) | 97 passed, 1 failed: unchanged OpenAI client-construction test rejects injected `socks5h` proxy scheme |
| `poetry run pytest` (isolated offline test environment) | **98 passed**; includes all existing 88 tests plus 10 new warning cases |
| `node --check src/app/document_jobs/static/app.js` | Passed |
| Temporary Node built-in VM/DOM smoke harness | Passed: seven simulated job states, plural/count text, partial labels, escaped-as-text filename, download controls and repeat refresh |
| ZIP byte comparison | Only the nine listed files changed; service diff limited to one metadata entry |

For the isolated pytest run, a temporary `sitecustomize.py` outside the repository first
blocked IPv4/IPv6 socket connections, then removed the six upper/lowercase HTTP, HTTPS
and ALL proxy variables from that test process. It was injected through `PYTHONPATH`
before running `poetry run pytest`. This isolates the pre-existing environment issue;
it does not change application code, dependencies or runtime proxy behavior.

Focused tests cover full-document warnings on both statuses, page scope/unassigned and
unavailable-page references, sequential/parallel equivalence, HTML-like warning values,
no-warning outputs, partial page context, persisted counts through both status endpoints,
no object reads during polling, and legacy defaults.

## 6. Visual checks and limits

Four synthetic HTML samples were rendered locally using MuPDF and visually inspected:
full partial document, individual partial page, SUCCEEDED document with warnings, and
SUCCEEDED document without warnings. Labels, page/block details, literal hostile strings
and retained content were visible. MuPDF is not a browser and does not validate browser
CSS/layout behavior.

An actual browser preview was attempted but the browser blocked the local address with
`net::ERR_BLOCKED_BY_CLIENT`. Browser UI layout/interaction therefore remains unverified;
the UI smoke checks used a simulated DOM, not a browser. No frontend framework was added.

Docker execution, live AWS behavior and real-PDF fidelity remain **NOT VERIFIED**.
There is no known code blocker for the next operator verification step.

## 7. Next step and deferred work

1. Review and apply the replacement files against the same current repository.
2. Verify Docker build, API and worker execution on the user's Docker-capable machine.
3. Configure the user's AWS environment, then run the first real
   PDF → Textract → structured document + HTML → download conversion.
4. Inspect actual output and warning presentation, including browser UI behavior.

Human review/editing remains planned for version 1, after the first real conversion run.
Further speculative hardening, recipe extraction, audit modules and LLM wrapper work
are deferred. Do not reopen the accepted lifecycle/capacity design as part of this slice.

# BatchLens — Stage 3: Local Manual Test Guide

This guide verifies the accepted local Stage 3 Extraction Review Workspace. It is a browser/manual acceptance guide, not a pharmaceutical validation protocol and not a production qualification procedure.

Use a fresh local data directory for a clean first run. Follow sections 7.1–7.5 of `docs/BatchLens-Stage3-Detailed-Local-Guide-EN.md` first. Keep the harness PowerShell window running while using the browser.

## 1. Test setup and expected starting state

Open the harness URL, for example:

```text
http://127.0.0.1:8767/documents/local-extraction-review
```

Expected:

- the **Extraction run** selector shows the submitted run;
- a reviewed HTML page is on the left;
- findings for the selected page are on the right;
- status is `Not approved` for a new run;
- `Save` is disabled until an edit exists;
- `Approve extraction result` is enabled only when there is a loaded, saved, non-dirty result.

Record the run label or its short local-job suffix before testing. It identifies the run later in the selector.

## 2. Page navigation and evidence focus

1. Use the page dropdown, next/previous arrows, and page dots.
2. Confirm the left HTML page and By-page findings change together.
3. Switch to **All findings**.
4. Select a finding from another page.

Expected:

- the workspace returns to **By page**;
- it opens the finding’s assigned page;
- the corresponding evidence is focused in the left HTML when source evidence exists;
- navigation and view switching do not change approval state.

## 3. Category visibility controls

1. In the legend, click **Material**.
2. Confirm material rows disappear from the right panel and material overlays disappear from the left HTML.
3. Confirm UO, Equipment, and Other remain visible.
4. Switch to **All findings** and confirm Material remains hidden there.
5. Click **Material** again.

Expected:

- the legend shows a non-color off state while disabled;
- re-enabling restores the Material rows and overlays;
- no `Unsaved` state appears;
- no Save action is needed;
- a browser refresh resets all categories to visible.

## 4. Add a manual finding and save it

1. Stay in **By page** mode and select a page.
2. Click **+ Add finding**.
3. Enter a non-empty text such as `manual review note` and choose a category.
4. Confirm the draft says it is unsaved.
5. Click **Save**.
6. Refresh the browser.

Expected:

- Add is available only in By page mode;
- the new finding is automatically assigned to the active page;
- no network save occurs before Save;
- the saved finding remains after refresh;
- it is marked `No document evidence` and has no fabricated left-pane highlight, even if identical text exists in the page.

## 5. Unsaved changes and approval protection

1. Edit one existing finding or the manual finding.
2. Confirm `Approve extraction result` is disabled.
3. Refresh the browser without clicking Save.

Expected:

- the unsaved browser edit is lost;
- the prior saved state remains;
- no unsaved edit can be silently included in approval.

## 6. Remove and restore

1. In By page mode, click **Remove** on an active finding.
2. Click **Save**.
3. Refresh the browser.
4. Confirm the finding is muted/struck through and has **Restore**.
5. Click **Restore**, then click **Save**.
6. Refresh again.

Expected:

- the removed finding is retained as a current-state tombstone until restored;
- the saved removed state survives reload;
- Restore reactivates the same finding;
- lexical origin/evidence for an imported finding is retained;
- removal is not an individual rejection or approval decision.

## 7. Download TXT

1. Ensure there are no unsaved edits.
2. Click **Download TXT**.
3. Open the downloaded text file.

Expected:

- the download is disabled while the UI is dirty;
- active saved findings are grouped by category;
- entries follow page order and then saved finding order;
- a manual addition contains `[no document evidence]`;
- removed findings are absent.

## 8. Final extraction-result approval

1. With no unsaved edits, click **Approve extraction result**.
2. Confirm the visible status becomes `Approved`.
3. Refresh the browser.
4. Edit one finding and click **Save**.

Expected:

- approval succeeds only for the saved current result;
- status remains `Approved` after refresh;
- the later effective Save changes status to `Not approved`;
- Stage 2 execution/publication outcome text does not change when approval changes.

## 9. Two runs of the same reviewed HTML

This test verifies per-run isolation.

1. Note the first run’s selector label and save/approve a distinguishable manual finding.
2. Stop the harness with `Ctrl+C`.
3. Run the same approved HTML again using the same data directory and `--run-extraction`.
4. The harness prints a new local-job ID and opens that new run.
5. Confirm the new run is `Not approved` and does not contain the first run’s manual finding.
6. Use the **Extraction run** selector to return to the first run.

Expected:

- the selector contains two distinguishable runs for the same HTML;
- the first run retains its own saved finding and approval state;
- the second run has its own independent current review;
- no `a current extraction review already exists for another published run` error appears.

## 10. Restart persistence

1. Stop the harness with `Ctrl+C`.
2. Start it again without `--run-extraction`, using the same data directory and approved-document root.
3. Open the printed URL and select the intended extraction run.

Expected:

- the selected run’s saved findings and approval state return;
- no new extraction runs merely because the harness restarted;
- the raw Stage 2/L13 artifact directories are not edited by review actions.

## 11. Result record

For each manual run, record only:

| Item | Record |
|---|---|
| Date/time |  |
| Data directory |  |
| Extraction-run label / local-job suffix |  |
| Action used |  |
| Tests 2–10 passed | Yes / No with brief note |
| Unexpected API/browser error | Exact message and reproduction step |

Do not treat a green UI state, successful local approval, or lexical occurrence as pharmaceutical validation, manufacturing batch release, regulatory approval, or a production audit record.

"""U1.2 local JSON persistence for the current Stage 3 extraction-review state."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.extraction_review.contracts import (
    ApproveExtractionResultCommand,
    InitializeReviewCommand,
    PatchFindingTextEdit,
    ReviewFindingRecord,
    SaveReviewEditsCommand,
    TransitionOutcomeKind,
)
from app.extraction_review.store import (
    CURRENT_REVIEW_FILENAME,
    REVIEWS_DIR_NAME,
    ExtractionReviewAlreadyExistsError,
    ExtractionReviewNotFoundError,
    ExtractionReviewStore,
    derive_workspace_key,
)
from tests.extraction_review.test_contracts import (
    NOW,
    REV_1,
    REV_2,
    document_source,
    lexical_finding,
    materials_extraction,
    published_run,
)

LATER = datetime(2026, 9, 29, 13, 0, 0, tzinfo=UTC)
REV_3 = "33333333-3333-4333-8333-333333333333"
JOB_ID = "job-1"


def _store(tmp_path: Path) -> ExtractionReviewStore:
    return ExtractionReviewStore(tmp_path)


def _create_command(
    *,
    findings: tuple[ReviewFindingRecord, ...] = (),
    revision_id: str = REV_1,
) -> InitializeReviewCommand:
    return InitializeReviewCommand(
        revision_id=revision_id,
        actor="system",
        created_at=NOW,
        document_source=document_source(),
        run=published_run(),
        extraction=materials_extraction(),
        findings=findings,
    )


def test_create_then_load(tmp_path: Path) -> None:
    store = _store(tmp_path)
    findings = (lexical_finding("f1", "water"), lexical_finding("f2", "ethanol"))
    created = store.create(_create_command(findings=findings))

    loaded = store.load(JOB_ID)
    assert loaded == created
    assert loaded.findings == findings
    assert loaded.approval is None
    assert loaded.current_revision_id == REV_1

    key = derive_workspace_key(JOB_ID)
    path = tmp_path / REVIEWS_DIR_NAME / key / CURRENT_REVIEW_FILENAME
    assert path.is_file()
    assert path == store.current_path(JOB_ID)


def test_create_refuses_overwrite(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_create_command(findings=(lexical_finding(),)))
    with pytest.raises(ExtractionReviewAlreadyExistsError):
        store.create(_create_command(findings=(lexical_finding(),)))


def test_load_missing_is_explicit_not_found(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ExtractionReviewNotFoundError):
        store.load(JOB_ID)


def test_save_persists_complete_state_and_clears_approval(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_create_command(findings=(lexical_finding("f1", "water"),)))
    approved = store.approve(
        JOB_ID,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_1,
            actor="approver",
            at=LATER,
            target_revision_id=REV_1,
        ),
    )
    assert approved.outcome is TransitionOutcomeKind.CHANGED
    assert store.load(JOB_ID).approval is not None

    saved = store.save_edits(
        JOB_ID,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="f1", display_text="WFI"),),
        ),
        new_revision_id=REV_2,
    )
    assert saved.outcome is TransitionOutcomeKind.CHANGED
    loaded = store.load(JOB_ID)
    assert loaded.current_revision_id == REV_2
    assert loaded.approval is None
    assert loaded.findings[0].current is not None
    assert loaded.findings[0].current.display_text == "WFI"
    assert loaded.findings[0].changed_by_user is not None


def test_approve_persists_approval_without_changing_findings(tmp_path: Path) -> None:
    store = _store(tmp_path)
    findings = (lexical_finding("f1", "water"),)
    store.create(_create_command(findings=findings))
    before = store.load(JOB_ID)

    result = store.approve(
        JOB_ID,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_1,
            actor="approver",
            at=LATER,
            target_revision_id=REV_1,
        ),
    )
    assert result.outcome is TransitionOutcomeKind.CHANGED
    loaded = store.load(JOB_ID)
    assert loaded.approval is not None
    assert loaded.approval.actor == "approver"
    assert loaded.approval.approved_revision_id == REV_1
    assert loaded.findings == before.findings
    assert loaded.current_revision_id == REV_1


def test_fresh_store_instance_reloads_latest_state(tmp_path: Path) -> None:
    first = _store(tmp_path)
    first.create(_create_command(findings=(lexical_finding("f1", "water"),)))
    first.save_edits(
        JOB_ID,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="f1", display_text="WFI"),),
        ),
        new_revision_id=REV_2,
    )
    first.approve(
        JOB_ID,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_2,
            actor="approver",
            at=LATER,
            target_revision_id=REV_2,
        ),
    )

    second = ExtractionReviewStore(tmp_path)
    loaded = second.load(JOB_ID)
    assert loaded.current_revision_id == REV_2
    assert loaded.approval is not None
    assert loaded.findings[0].current is not None
    assert loaded.findings[0].current.display_text == "WFI"


def test_non_changed_outcomes_leave_stored_bytes_unchanged(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_create_command(findings=(lexical_finding("f1", "water"),)))
    path = store.current_path(JOB_ID)
    before = path.read_bytes()

    stale_save = store.save_edits(
        JOB_ID,
        SaveReviewEditsCommand(
            expected_revision_id=REV_2,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="f1", display_text="WFI"),),
        ),
        new_revision_id=REV_3,
    )
    assert stale_save.outcome is TransitionOutcomeKind.CONFLICT
    assert path.read_bytes() == before

    unchanged = store.save_edits(
        JOB_ID,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="f1", display_text="water"),),
        ),
        new_revision_id=REV_2,
    )
    assert unchanged.outcome is TransitionOutcomeKind.UNCHANGED
    assert path.read_bytes() == before

    validation = store.save_edits(
        JOB_ID,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="missing", display_text="x"),),
        ),
        new_revision_id=REV_2,
    )
    assert validation.outcome is TransitionOutcomeKind.VALIDATION_ERROR
    assert path.read_bytes() == before

    store.approve(
        JOB_ID,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_1,
            actor="approver",
            at=LATER,
            target_revision_id=REV_1,
        ),
    )
    after_approve = path.read_bytes()
    assert after_approve != before

    stale_approve = store.approve(
        JOB_ID,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_2,
            actor="approver",
            at=LATER,
            target_revision_id=REV_2,
        ),
    )
    assert stale_approve.outcome is TransitionOutcomeKind.CONFLICT
    assert path.read_bytes() == after_approve

    repeated = store.approve(
        JOB_ID,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_1,
            actor="approver",
            at=LATER,
            target_revision_id=REV_1,
        ),
    )
    assert repeated.outcome is TransitionOutcomeKind.UNCHANGED
    assert path.read_bytes() == after_approve


def test_one_thousand_findings_save_and_reload(tmp_path: Path) -> None:
    store = _store(tmp_path)
    findings = tuple(lexical_finding(f"f-{index}", f"m-{index}") for index in range(1_000))
    store.create(_create_command(findings=findings))
    store.save_edits(
        JOB_ID,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="f-500", display_text="updated"),),
        ),
        new_revision_id=REV_2,
    )

    reloaded = ExtractionReviewStore(tmp_path).load(JOB_ID)
    assert len(reloaded.findings) == 1_000
    by_id = {item.finding_id: item for item in reloaded.findings}
    assert by_id["f-500"].current is not None
    assert by_id["f-500"].current.display_text == "updated"


def test_no_historical_revision_or_approval_files_created(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_create_command(findings=(lexical_finding(),)))
    store.save_edits(
        JOB_ID,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="finding-1", display_text="WFI"),),
        ),
        new_revision_id=REV_2,
    )
    store.approve(
        JOB_ID,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_2,
            actor="approver",
            at=LATER,
            target_revision_id=REV_2,
        ),
    )

    workspace = tmp_path / REVIEWS_DIR_NAME / derive_workspace_key(JOB_ID)
    names = sorted(path.name for path in workspace.iterdir())
    assert names == [CURRENT_REVIEW_FILENAME]
    assert not (workspace / "revisions").exists()
    assert not (workspace / "approvals").exists()
    assert not list(tmp_path.rglob("*.tmp"))

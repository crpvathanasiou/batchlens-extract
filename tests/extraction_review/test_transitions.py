"""Pure Stage 3 extraction-review current-state transitions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.extraction_review.contracts import (
    MAX_FINDING_EDITS_PER_SAVE,
    AddedByUserProvenance,
    AddFindingEdit,
    ApproveExtractionResultCommand,
    AssignedPage,
    ChangedByUserProvenance,
    DocumentSourceReference,
    ExtractionResultApproval,
    ExtractionRunReference,
    FindingEvidenceStatus,
    InitializeReviewCommand,
    LexicalFindingOrigin,
    PatchFindingTextEdit,
    RemovedByUserProvenance,
    RemoveFindingEdit,
    ReplaceFindingEdit,
    RestoreFindingEdit,
    ReviewApprovalState,
    ReviewFindingRecord,
    SaveReviewEditsCommand,
    TransitionOutcomeKind,
    UnassignedPage,
    UserAddedFindingOrigin,
    UserFacingFinding,
)
from app.extraction_review.transitions import (
    approve_extraction_result,
    initialize_review_workspace,
    save_review_edits,
)
from app.lexical_extraction.contracts import (
    Component,
    ComponentResult,
    ExtractionOutcome,
    ExtractionOutcomeRecord,
    FinalManifestClaim,
    PublicationRecord,
    PublicationStatus,
    SafeStructuredError,
)
from tests.extraction_review.test_contracts import (
    NOW,
    REV_1,
    REV_2,
    binding,
    document_source,
    lexical_finding,
    materials_extraction,
    published_run,
    run_provenance,
)

LATER = datetime(2026, 9, 29, 13, 0, 0, tzinfo=UTC)


def _partial_extraction() -> ExtractionOutcomeRecord:
    return ExtractionOutcomeRecord(
        overall=ExtractionOutcome.PARTIAL,
        components=(
            ComponentResult(
                component=Component.MATERIALS,
                outcome=ExtractionOutcome.COMPLETED,
                match_count=2,
            ),
            ComponentResult(
                component=Component.EQUIPMENT,
                outcome=ExtractionOutcome.FAILED,
                error=SafeStructuredError(
                    code="COMPONENT_FAILED",
                    message="synthetic failure",
                    component=Component.EQUIPMENT,
                    retryable=False,
                ),
            ),
        ),
    )


def _zero_hit_extraction() -> ExtractionOutcomeRecord:
    return ExtractionOutcomeRecord(
        overall=ExtractionOutcome.COMPLETED,
        components=(
            ComponentResult(
                component=Component.MATERIALS,
                outcome=ExtractionOutcome.COMPLETED,
                match_count=0,
            ),
        ),
    )


def _all_failed_extraction() -> ExtractionOutcomeRecord:
    return ExtractionOutcomeRecord(
        overall=ExtractionOutcome.FAILED,
        components=(
            ComponentResult(
                component=Component.MATERIALS,
                outcome=ExtractionOutcome.FAILED,
                error=SafeStructuredError(
                    code="COMPONENT_FAILED",
                    message="synthetic failure",
                    component=Component.MATERIALS,
                    retryable=False,
                ),
            ),
        ),
    )


def _init(
    *,
    findings: tuple[ReviewFindingRecord, ...] = (),
    extraction: ExtractionOutcomeRecord | None = None,
    run: ExtractionRunReference | None = None,
    source: DocumentSourceReference | None = None,
    revision_id: str = REV_1,
):
    return initialize_review_workspace(
        InitializeReviewCommand(
            revision_id=revision_id,
            actor="system",
            created_at=NOW,
            document_source=source or document_source(),
            run=run or published_run(),
            extraction=extraction or materials_extraction(),
            findings=findings,
        )
    ).state


def test_initialize_with_complete_finding_list() -> None:
    findings = (lexical_finding("f1"), lexical_finding("f2", "ethanol"))
    state = _init(findings=findings)
    assert state.current_revision_id == REV_1
    assert state.findings == findings
    assert state.approval is None
    assert state.approval_state is ReviewApprovalState.NOT_APPROVED


def test_initialize_partial_and_zero_hit_are_unapproved() -> None:
    partial = _init(
        extraction=_partial_extraction(),
        run=published_run(
            requested_components=[Component.MATERIALS.value, Component.EQUIPMENT.value],
            resolved_components=[Component.MATERIALS.value, Component.EQUIPMENT.value],
        ),
    )
    zero = _init(extraction=_zero_hit_extraction(), findings=())
    assert partial.approval_state is ReviewApprovalState.NOT_APPROVED
    assert zero.approval_state is ReviewApprovalState.NOT_APPROVED
    assert zero.findings == ()


def test_approval_does_not_change_findings() -> None:
    findings = (lexical_finding(),)
    state = _init(findings=findings)
    result = approve_extraction_result(
        state,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_1,
            actor="approver",
            at=LATER,
            target_revision_id=REV_1,
        ),
    )
    assert result.outcome is TransitionOutcomeKind.CHANGED
    assert result.state is not None
    assert result.approval is not None
    assert result.approval == ExtractionResultApproval(
        actor="approver",
        at=LATER,
        approved_revision_id=REV_1,
    )
    assert result.state.findings == findings
    assert result.state.current_revision_id == REV_1


def test_effective_save_updates_findings_new_revision_and_clears_approval() -> None:
    state = _init(findings=(lexical_finding("f1", "water"), lexical_finding("f2", "ethanol")))
    approved = approve_extraction_result(
        state,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_1,
            actor="approver",
            at=LATER,
            target_revision_id=REV_1,
        ),
    ).state
    assert approved is not None
    assert approved.approval is not None

    saved = save_review_edits(
        approved,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="f1", display_text="WFI"),),
        ),
        new_revision_id=REV_2,
    )
    assert saved.outcome is TransitionOutcomeKind.CHANGED
    assert saved.state is not None
    assert saved.state.current_revision_id == REV_2
    assert saved.state.approval is None
    assert saved.state.findings[0].current is not None
    assert saved.state.findings[0].current.display_text == "WFI"
    assert saved.state.findings[1].current is not None
    assert saved.state.findings[1].current.display_text == "ethanol"
    # Prior approval and prior revision id are discarded from current state.
    assert approved.current_revision_id == REV_1
    assert approved.approval is not None


def test_noop_save_retains_approval() -> None:
    state = _init(findings=(lexical_finding("f1", "water"),))
    approved = approve_extraction_result(
        state,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_1,
            actor="approver",
            at=LATER,
            target_revision_id=REV_1,
        ),
    ).state
    assert approved is not None
    result = save_review_edits(
        approved,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="f1", display_text="water"),),
        ),
        new_revision_id=REV_2,
    )
    assert result.outcome is TransitionOutcomeKind.UNCHANGED
    assert result.state is approved
    assert approved.approval is not None


def test_stale_save_and_stale_approval_conflict() -> None:
    state = _init(findings=(lexical_finding(),))
    saved = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="finding-1", display_text="WFI"),),
        ),
        new_revision_id=REV_2,
    )
    assert saved.state is not None

    stale_save = save_review_edits(
        saved.state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="finding-1", display_text="other"),),
        ),
        new_revision_id="33333333-3333-4333-8333-333333333333",
    )
    assert stale_save.outcome is TransitionOutcomeKind.CONFLICT

    stale_approve = approve_extraction_result(
        saved.state,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_1,
            actor="approver",
            at=LATER,
            target_revision_id=REV_1,
        ),
    )
    assert stale_approve.outcome is TransitionOutcomeKind.CONFLICT


def test_patch_text_preserves_original_lexical_text_and_evidence() -> None:
    state = _init(findings=(lexical_finding("f1", "water"),))
    original_origin = state.findings[0].origin
    assert isinstance(original_origin, LexicalFindingOrigin)
    saved = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="f1", display_text="purified water"),),
        ),
        new_revision_id=REV_2,
    )
    assert saved.state is not None
    finding = saved.state.findings[0]
    current = finding.current
    assert current is not None
    assert current.display_text == "purified water"
    assert current.page_assignment == AssignedPage(page_number=1)
    assert current.evidence_status is FindingEvidenceStatus.DOCUMENT_EVIDENCE
    assert isinstance(finding.origin, LexicalFindingOrigin)
    assert finding.origin == original_origin
    assert finding.origin.original_matched_text == "water"
    assert finding.origin.evidence == original_origin.evidence
    assert finding.changed_by_user == ChangedByUserProvenance(actor="reviewer", at=LATER)


def test_replace_can_unassign_page_explicitly() -> None:
    state = _init(findings=(lexical_finding("f1", "water"),))
    original_origin = state.findings[0].origin
    saved = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(
                ReplaceFindingEdit(
                    finding_id="f1",
                    current=UserFacingFinding(
                        component=Component.MATERIALS,
                        display_text="water",
                        page_assignment=UnassignedPage(),
                        evidence_status=FindingEvidenceStatus.NO_DOCUMENT_EVIDENCE,
                    ),
                ),
            ),
        ),
        new_revision_id=REV_2,
    )
    assert saved.state is not None
    current = saved.state.findings[0].current
    assert current is not None
    assert current.page_assignment == UnassignedPage()
    assert current.evidence_status is FindingEvidenceStatus.NO_DOCUMENT_EVIDENCE
    assert saved.state.findings[0].origin == original_origin
    assert saved.state.findings[0].changed_by_user == ChangedByUserProvenance(
        actor="reviewer",
        at=LATER,
    )


def test_user_added_via_add_and_collision_rejected() -> None:
    state = _init(findings=(lexical_finding("f1"),))
    saved = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(
                AddFindingEdit(
                    finding_id="user-1",
                    component=Component.MATERIALS,
                    display_text="manual",
                    page_assignment=AssignedPage(page_number=3),
                    evidence_status=FindingEvidenceStatus.NO_DOCUMENT_EVIDENCE,
                ),
            ),
        ),
        new_revision_id=REV_2,
    )
    assert saved.outcome is TransitionOutcomeKind.CHANGED
    assert saved.state is not None
    assert len(saved.state.findings) == 2
    added = saved.state.findings[1]
    assert isinstance(added.origin, UserAddedFindingOrigin)
    assert added.added_by_user == AddedByUserProvenance(actor="reviewer", at=LATER)
    assert added.changed_by_user is None

    collision = save_review_edits(
        saved.state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_2,
            actor="reviewer",
            at=LATER,
            edits=(
                AddFindingEdit(
                    finding_id="f1",
                    component=Component.MATERIALS,
                    display_text="dup",
                    page_assignment=UnassignedPage(),
                    evidence_status=FindingEvidenceStatus.NO_DOCUMENT_EVIDENCE,
                ),
            ),
        ),
        new_revision_id="33333333-3333-4333-8333-333333333333",
    )
    assert collision.outcome is TransitionOutcomeKind.VALIDATION_ERROR


def test_add_rejects_document_evidence_claim() -> None:
    state = _init(findings=())
    result = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(
                AddFindingEdit(
                    finding_id="user-1",
                    component=Component.MATERIALS,
                    display_text="bad",
                    page_assignment=UnassignedPage(),
                    evidence_status=FindingEvidenceStatus.DOCUMENT_EVIDENCE,
                ),
            ),
        ),
        new_revision_id=REV_2,
    )
    assert result.outcome is TransitionOutcomeKind.VALIDATION_ERROR


def test_remove_marks_finding_removed_with_provenance_tombstone() -> None:
    state = _init(findings=(lexical_finding("f1", "water"),))
    original_origin = state.findings[0].origin
    saved = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(RemoveFindingEdit(finding_id="f1", note="not a material"),),
        ),
        new_revision_id=REV_2,
    )
    assert saved.state is not None
    tombstone = saved.state.findings[0]
    assert tombstone.removed is True
    assert tombstone.is_active is False
    assert tombstone.current is not None
    assert tombstone.current.display_text == "water"
    assert tombstone.origin == original_origin
    assert tombstone.removed_by_user == RemovedByUserProvenance(
        actor="reviewer",
        at=LATER,
        note="not a material",
    )


def test_restore_returns_removed_finding_to_active() -> None:
    state = _init(findings=(lexical_finding("f1", "water"),))
    removed = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(RemoveFindingEdit(finding_id="f1"),),
        ),
        new_revision_id=REV_2,
    )
    assert removed.state is not None
    restored = save_review_edits(
        removed.state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_2,
            actor="reviewer",
            at=LATER,
            edits=(RestoreFindingEdit(finding_id="f1"),),
        ),
        new_revision_id="33333333-3333-4333-8333-333333333333",
    )
    assert restored.outcome is TransitionOutcomeKind.CHANGED
    assert restored.state is not None
    finding = restored.state.findings[0]
    assert finding.removed is False
    assert finding.removed_by_user is None
    assert finding.current is not None
    assert finding.current.display_text == "water"


def test_effective_save_rejects_unchanged_replacement_revision_id() -> None:
    state = _init(findings=(lexical_finding("f1", "water"),))
    result = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="f1", display_text="WFI"),),
        ),
        new_revision_id=REV_1,
    )
    assert result.outcome is TransitionOutcomeKind.VALIDATION_ERROR
    assert result.state is None
    assert result.message is not None
    assert "new_revision_id must differ" in result.message


def test_repeated_approval_is_unchanged() -> None:
    state = _init(findings=(lexical_finding(),))
    first = approve_extraction_result(
        state,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_1,
            actor="approver",
            at=LATER,
            target_revision_id=REV_1,
        ),
    )
    assert first.state is not None
    second = approve_extraction_result(
        first.state,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_1,
            actor="approver",
            at=LATER,
            target_revision_id=REV_1,
        ),
    )
    assert second.outcome is TransitionOutcomeKind.UNCHANGED
    assert second.approval == first.approval


def test_approve_rejects_mismatched_target_revision() -> None:
    state = _init(findings=(lexical_finding(),))
    result = approve_extraction_result(
        state,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_1,
            actor="approver",
            at=LATER,
            target_revision_id=REV_2,
        ),
    )
    assert result.outcome is TransitionOutcomeKind.VALIDATION_ERROR


def test_new_run_isolation() -> None:
    a = _init(run=published_run(run_id="run-a"), findings=(lexical_finding(),))
    b = _init(run=published_run(run_id="run-b"), findings=(lexical_finding(),))
    assert a.run_id == "run-a"
    assert b.run_id == "run-b"
    assert a.binding != b.binding


def test_failed_publication_cannot_initialize() -> None:
    with pytest.raises(ValueError, match="completed published runs"):
        initialize_review_workspace(
            InitializeReviewCommand(
                revision_id=REV_1,
                actor="system",
                created_at=NOW,
                document_source=document_source(),
                run=ExtractionRunReference(
                    run=run_provenance(),
                    publication=PublicationRecord(status=PublicationStatus.FAILED),
                    published_manifest=None,
                ),
                extraction=materials_extraction(),
                findings=(),
            )
        )


def test_completed_run_without_published_manifest_cannot_initialize() -> None:
    with pytest.raises(ValidationError, match="published_manifest"):
        ExtractionRunReference(
            run=run_provenance(),
            publication=PublicationRecord(
                status=PublicationStatus.COMPLETED,
                final_manifest=FinalManifestClaim(manifest_id="manifest-1"),
            ),
            published_manifest=None,
        )


def test_all_failed_published_run_cannot_initialize() -> None:
    with pytest.raises(ValueError, match="completed extraction component"):
        _init(extraction=_all_failed_extraction())


def test_html_only_source_can_initialize_save_and_approve() -> None:
    state = _init(
        source=document_source(document_hash=None),
        findings=(lexical_finding(),),
    )
    assert state.binding.document_source.document_hash is None
    saved = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="finding-1", display_text="WFI"),),
        ),
        new_revision_id=REV_2,
    )
    assert saved.state is not None
    approved = approve_extraction_result(
        saved.state,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_2,
            actor="approver",
            at=LATER,
            target_revision_id=REV_2,
        ),
    )
    assert approved.outcome is TransitionOutcomeKind.CHANGED
    assert approved.state is not None
    assert approved.state.binding.document_source.document_hash is None


def test_page_assigned_no_evidence_add_save_approve() -> None:
    state = _init(findings=(lexical_finding("page-only", "note", page_number=2, with_span=False),))
    saved = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(
                AddFindingEdit(
                    finding_id="user-1",
                    component=Component.MATERIALS,
                    display_text="manual",
                    page_assignment=AssignedPage(page_number=4),
                    evidence_status=FindingEvidenceStatus.NO_DOCUMENT_EVIDENCE,
                ),
            ),
        ),
        new_revision_id=REV_2,
    )
    assert saved.state is not None
    approved = approve_extraction_result(
        saved.state,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_2,
            actor="approver",
            at=LATER,
            target_revision_id=REV_2,
        ),
    )
    assert approved.outcome is TransitionOutcomeKind.CHANGED


def test_one_thousand_findings_save() -> None:
    findings = tuple(lexical_finding(f"f-{index}", f"m-{index}") for index in range(1_000))
    state = _init(findings=findings)
    saved = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="f-500", display_text="updated"),),
        ),
        new_revision_id=REV_2,
    )
    assert saved.outcome is TransitionOutcomeKind.CHANGED
    assert saved.state is not None
    assert len(saved.state.findings) == 1_000
    by_id = {item.finding_id: item for item in saved.state.findings}
    assert by_id["f-500"].current is not None
    assert by_id["f-500"].current.display_text == "updated"


def test_fifty_edits_valid_fifty_first_rejected_at_command() -> None:
    findings = tuple(lexical_finding(f"f-{index}", f"m-{index}") for index in range(51))
    state = _init(findings=findings)
    edits = tuple(
        PatchFindingTextEdit(finding_id=f"f-{index}", display_text=f"n-{index}")
        for index in range(MAX_FINDING_EDITS_PER_SAVE)
    )
    saved = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=edits,
        ),
        new_revision_id=REV_2,
    )
    assert saved.outcome is TransitionOutcomeKind.CHANGED
    with pytest.raises(ValidationError):
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=edits + (PatchFindingTextEdit(finding_id="f-50", display_text="x"),),
        )


def test_source_run_provenance_immutable_across_save_and_approve() -> None:
    source = document_source()
    run = published_run()
    state = _init(source=source, run=run, findings=(lexical_finding(),))
    saved = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="finding-1", display_text="WFI"),),
        ),
        new_revision_id=REV_2,
    )
    assert saved.state is not None
    approved = approve_extraction_result(
        saved.state,
        ApproveExtractionResultCommand(
            expected_revision_id=REV_2,
            actor="approver",
            at=LATER,
            target_revision_id=REV_2,
        ),
    )
    assert approved.state is not None
    assert approved.state.binding.document_source == source
    assert approved.state.binding.run == run
    assert approved.state.binding == binding(
        document_source=source,
        run=run,
        extraction=materials_extraction(),
    )


def test_missing_finding_rejected() -> None:
    state = _init(findings=(lexical_finding("f1"),))
    result = save_review_edits(
        state,
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=LATER,
            edits=(PatchFindingTextEdit(finding_id="missing", display_text="x"),),
        ),
        new_revision_id=REV_2,
    )
    assert result.outcome is TransitionOutcomeKind.VALIDATION_ERROR

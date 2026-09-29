"""Pure Stage 3 extraction-review transitions (no I/O, clocks, or storage).

Mutations replace the single current state. Effective Save discards the prior
approval. There is no revision history, delta chain, or retry ledger.
"""

from __future__ import annotations

from app.extraction_review.contracts import (
    AddedByUserProvenance,
    AddFindingEdit,
    ApproveExtractionResultCommand,
    ApproveExtractionResultResult,
    ChangedByUserProvenance,
    ExtractionResultApproval,
    ExtractionReviewState,
    FindingEvidenceStatus,
    InitializeReviewCommand,
    InitializeReviewResult,
    PatchFindingTextEdit,
    RemovedByUserProvenance,
    RemoveFindingEdit,
    ReviewFindingRecord,
    SaveReviewEditsCommand,
    SaveReviewEditsResult,
    TransitionOutcomeKind,
    UserAddedFindingOrigin,
    UserFacingFinding,
    WorkspaceBinding,
    has_usable_completed_component,
    is_reviewable_publication,
)
from app.lexical_extraction.contracts import validate_resolved_component_coverage


def initialize_review_workspace(command: InitializeReviewCommand) -> InitializeReviewResult:
    if not is_reviewable_publication(command.run):
        raise ValueError(
            "only completed published runs with lexical-manifest SHA-256 initialize a review"
        )
    validate_resolved_component_coverage(command.run.run, command.extraction)
    if not has_usable_completed_component(command.extraction):
        raise ValueError("initialization requires at least one completed extraction component")
    if command.document_source.reviewed_html.html_sha256 != command.run.run.input_html_sha256:
        raise ValueError("reviewed HTML sha256 must match the run input_html_sha256")

    binding = WorkspaceBinding(
        document_source=command.document_source,
        run=command.run,
        extraction=command.extraction,
    )
    state = ExtractionReviewState(
        binding=binding,
        current_revision_id=command.revision_id,
        findings=command.findings,
        approval=None,
    )
    return InitializeReviewResult(state=state)


def save_review_edits(
    state: ExtractionReviewState,
    command: SaveReviewEditsCommand,
    *,
    new_revision_id: str,
) -> SaveReviewEditsResult:
    if command.expected_revision_id != state.current_revision_id:
        return SaveReviewEditsResult(
            outcome=TransitionOutcomeKind.CONFLICT,
            message="expected_revision_id does not match current saved revision",
        )
    if not command.edits:
        return SaveReviewEditsResult(outcome=TransitionOutcomeKind.UNCHANGED, state=state)

    try:
        updated_findings, changed = _apply_edits_to_findings(state.findings, command)
    except ValueError as exc:
        return SaveReviewEditsResult(
            outcome=TransitionOutcomeKind.VALIDATION_ERROR,
            message=str(exc),
        )

    if not changed:
        return SaveReviewEditsResult(outcome=TransitionOutcomeKind.UNCHANGED, state=state)

    if new_revision_id == state.current_revision_id:
        return SaveReviewEditsResult(
            outcome=TransitionOutcomeKind.VALIDATION_ERROR,
            message="new_revision_id must differ from the current saved revision",
        )

    new_state = ExtractionReviewState(
        binding=state.binding,
        current_revision_id=new_revision_id,
        findings=updated_findings,
        approval=None,
    )
    return SaveReviewEditsResult(outcome=TransitionOutcomeKind.CHANGED, state=new_state)


def approve_extraction_result(
    state: ExtractionReviewState,
    command: ApproveExtractionResultCommand,
) -> ApproveExtractionResultResult:
    if command.expected_revision_id != state.current_revision_id:
        return ApproveExtractionResultResult(
            outcome=TransitionOutcomeKind.CONFLICT,
            message="expected_revision_id does not match current saved revision",
        )
    if command.target_revision_id != state.current_revision_id:
        return ApproveExtractionResultResult(
            outcome=TransitionOutcomeKind.VALIDATION_ERROR,
            message="approval target_revision_id must match the current saved revision",
        )

    prior = state.approval
    if prior is not None and prior.approved_revision_id == command.target_revision_id:
        return ApproveExtractionResultResult(
            outcome=TransitionOutcomeKind.UNCHANGED,
            state=state,
            approval=prior,
        )

    approval = ExtractionResultApproval(
        actor=command.actor,
        at=command.at,
        approved_revision_id=command.target_revision_id,
    )
    new_state = ExtractionReviewState(
        binding=state.binding,
        current_revision_id=state.current_revision_id,
        findings=state.findings,
        approval=approval,
    )
    return ApproveExtractionResultResult(
        outcome=TransitionOutcomeKind.CHANGED,
        state=new_state,
        approval=approval,
    )


def _apply_edits_to_findings(
    findings: tuple[ReviewFindingRecord, ...],
    command: SaveReviewEditsCommand,
) -> tuple[tuple[ReviewFindingRecord, ...], bool]:
    by_id = {finding.finding_id: finding for finding in findings}
    if len(by_id) != len(findings):
        raise ValueError("duplicate finding_id in current findings")

    changed = False
    for edit in command.edits:
        if isinstance(edit, AddFindingEdit):
            if edit.finding_id in by_id:
                raise ValueError("add finding_id collides with existing finding")
            if edit.evidence_status is FindingEvidenceStatus.DOCUMENT_EVIDENCE:
                raise ValueError("user-added findings cannot claim document_evidence")
            current = UserFacingFinding(
                component=edit.component,
                display_text=edit.display_text,
                page_assignment=edit.page_assignment,
                evidence_status=edit.evidence_status,
            )
            by_id[edit.finding_id] = ReviewFindingRecord(
                finding_id=edit.finding_id,
                origin=UserAddedFindingOrigin(),
                current=current,
                added_by_user=AddedByUserProvenance(actor=command.actor, at=command.at),
            )
            changed = True
            continue

        existing = by_id.get(edit.finding_id)
        if existing is None:
            raise ValueError("missing finding for required finding_id")
        if existing.removed:
            raise ValueError("cannot edit a removed finding")
        assert existing.current is not None

        if isinstance(edit, RemoveFindingEdit):
            by_id[edit.finding_id] = ReviewFindingRecord(
                finding_id=existing.finding_id,
                origin=existing.origin,
                current=None,
                removed=True,
                added_by_user=existing.added_by_user,
                changed_by_user=existing.changed_by_user,
                removed_by_user=RemovedByUserProvenance(
                    actor=command.actor,
                    at=command.at,
                    note=edit.note,
                ),
            )
            changed = True
            continue

        if isinstance(edit, PatchFindingTextEdit):
            if edit.display_text == existing.current.display_text:
                continue
            new_current = UserFacingFinding(
                component=existing.current.component,
                display_text=edit.display_text,
                page_assignment=existing.current.page_assignment,
                evidence_status=existing.current.evidence_status,
            )
        else:
            new_current = edit.current
            if new_current == existing.current:
                continue

        by_id[edit.finding_id] = ReviewFindingRecord(
            finding_id=existing.finding_id,
            origin=existing.origin,
            current=new_current,
            removed=False,
            added_by_user=existing.added_by_user,
            changed_by_user=ChangedByUserProvenance(actor=command.actor, at=command.at),
        )
        changed = True

    ordered: list[ReviewFindingRecord] = []
    seen: set[str] = set()
    for finding in findings:
        ordered.append(by_id[finding.finding_id])
        seen.add(finding.finding_id)
    for edit in command.edits:
        if isinstance(edit, AddFindingEdit) and edit.finding_id not in seen:
            ordered.append(by_id[edit.finding_id])
            seen.add(edit.finding_id)
    return tuple(ordered), changed

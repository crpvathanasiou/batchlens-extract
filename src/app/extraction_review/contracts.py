"""Stage 3 extraction-review contracts — current-state MVP.

Stage 3 keeps one current review state only: the complete finding list, immutable
source/run/Stage 2 provenance, one current saved revision id (for stale Save
detection), and either no approval or one current approval of that revision.

Historical revision chains, delta-only saves, parent links, approval transition
ledgers, operation retry receipts, and version listing are intentionally absent.

These models do not read artifacts, verify hashes on disk, execute lexical
extraction, or persist data.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.lexical_extraction.contracts import (
    CharSpan,
    Component,
    ExtractionOutcome,
    ExtractionOutcomeRecord,
    Preset,
    PublicationRecord,
    PublicationStatus,
    ReviewedHtmlV1Input,
    RunProvenance,
    Sha256Hex,
    validate_resolved_component_coverage,
)

CONTRACT_SCHEMA_VERSION = "batchlens.extraction-review.v1"
REVISION_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"

MAX_FINDINGS_PER_REVIEW = 5_000
MAX_FINDING_EDITS_PER_SAVE = 50
MAX_FINDING_DISPLAY_TEXT = 10_000
MAX_CANDIDATE_REFS_PER_FINDING = 8
MAX_EDIT_NOTE_LENGTH = 2_000


class ExtractionReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


RevisionId = Annotated[str, Field(pattern=REVISION_ID_PATTERN)]
ContentFingerprint = Annotated[str, Field(pattern=FINGERPRINT_PATTERN)]


class ReviewApprovalState(StrEnum):
    NOT_APPROVED = "not_approved"
    APPROVED = "approved"


class ExtractionReviewAction(StrEnum):
    EXTRACT_UNIT_OPERATIONS = "extract_unit_operations"
    EXTRACT_MATERIALS = "extract_materials"
    EXTRACT_EQUIPMENT = "extract_equipment"
    EXTRACT_ALL = "extract_all"


_ACTION_PRESET: dict[ExtractionReviewAction, Preset] = {
    ExtractionReviewAction.EXTRACT_UNIT_OPERATIONS: Preset.UNIT_OPERATIONS_WITH_STEPS,
    ExtractionReviewAction.EXTRACT_MATERIALS: Preset.MATERIALS_WITH_QUANTITIES,
    ExtractionReviewAction.EXTRACT_EQUIPMENT: Preset.EQUIPMENT_WITH_PARAMETERS,
    ExtractionReviewAction.EXTRACT_ALL: Preset.FULL,
}


def action_to_preset(action: ExtractionReviewAction) -> Preset:
    return _ACTION_PRESET[action]


def fuzzy_extraction_default_enabled() -> bool:
    return False


class DocumentSourceReference(ExtractionReviewModel):
    """Stage 3 source binding.

    ``document_hash`` is optional Stage 1 canonical reviewed-document identity when the
    review JSON is unavailable. It is never fabricated and never filled from HTML SHA-256.
    ``reviewed_html`` (including HTML-byte SHA-256) remains mandatory.
    """

    job_id: Annotated[str, Field(min_length=1)]
    document_hash: ContentFingerprint | None = None
    reviewed_html: ReviewedHtmlV1Input

    @model_validator(mode="after")
    def identity_rules(self) -> Self:
        if self.job_id != self.reviewed_html.job_id:
            raise ValueError("job_id must match reviewed_html.job_id")
        return self


class PublishedManifestReference(ExtractionReviewModel):
    """Exact lexical-manifest identity. SHA-256 is recorded provenance, not verified here."""

    manifest_id: Annotated[str, Field(min_length=1)]
    manifest_sha256: Sha256Hex


class ExtractionRunReference(ExtractionReviewModel):
    run: RunProvenance
    publication: PublicationRecord
    published_manifest: PublishedManifestReference | None = None

    @model_validator(mode="after")
    def publication_claims_match(self) -> Self:
        if self.publication.status is PublicationStatus.COMPLETED:
            claim = self.publication.final_manifest
            if claim is None:
                raise ValueError("completed publication requires a final manifest claim")
            if self.published_manifest is None:
                raise ValueError("completed Stage 3 run requires published_manifest with SHA-256")
            if self.published_manifest.manifest_id != claim.manifest_id:
                raise ValueError("published manifest id must match the publication claim")
        elif self.published_manifest is not None:
            raise ValueError("failed or interrupted publication cannot carry manifest reference")
        return self


class WorkspaceBinding(ExtractionReviewModel):
    """Immutable source/run/outcome provenance for one current review state."""

    document_source: DocumentSourceReference
    run: ExtractionRunReference
    extraction: ExtractionOutcomeRecord

    @model_validator(mode="after")
    def source_run_outcome_agree(self) -> Self:
        if self.document_source.reviewed_html.html_sha256 != self.run.run.input_html_sha256:
            raise ValueError("reviewed HTML sha256 must match the run input_html_sha256")
        validate_resolved_component_coverage(self.run.run, self.extraction)
        return self


class CatalogueCandidateReference(ExtractionReviewModel):
    candidate_kind: Annotated[str, Field(min_length=1)]
    snapshot_id: Annotated[str, Field(min_length=1)]
    row_id: Annotated[str, Field(min_length=1)]
    matched_term: Annotated[str, Field(min_length=1)]


class OriginalLexicalEvidence(ExtractionReviewModel):
    occurrence_id: Annotated[str, Field(min_length=1)]
    occurrence_kind: Literal["dictionary", "unit", "value"]
    block_node_id: Annotated[str, Field(min_length=1)] | None = None
    page_number: Annotated[int, Field(ge=1)] | None = None
    location: CharSpan | None = None
    candidate_refs: tuple[CatalogueCandidateReference, ...] = Field(
        default_factory=tuple,
        max_length=MAX_CANDIDATE_REFS_PER_FINDING,
    )

    @model_validator(mode="after")
    def evidence_shape(self) -> Self:
        if self.location is None:
            if self.block_node_id is not None:
                raise ValueError("no span requires no block_node_id")
            return self
        if self.block_node_id is None:
            raise ValueError("document evidence requires block_node_id")
        return self


class LexicalFindingOrigin(ExtractionReviewModel):
    """Immutable Stage 2 lexical origin.

    ``original_matched_text`` and ``evidence`` are fixed at import and survive later
    edits to the user-facing ``current`` values.
    """

    kind: Literal["lexical"] = "lexical"
    evidence: OriginalLexicalEvidence
    original_matched_text: Annotated[str, Field(min_length=1, max_length=MAX_FINDING_DISPLAY_TEXT)]

    @model_validator(mode="after")
    def original_text_agrees_with_span(self) -> Self:
        location = self.evidence.location
        if location is not None and self.original_matched_text != location.matched_text:
            raise ValueError("original_matched_text must match evidence location matched_text")
        return self


class UserAddedFindingOrigin(ExtractionReviewModel):
    kind: Literal["user_added"] = "user_added"


FindingOrigin = Annotated[
    LexicalFindingOrigin | UserAddedFindingOrigin,
    Field(discriminator="kind"),
]


class AddedByUserProvenance(ExtractionReviewModel):
    """Provenance for a finding introduced by Save (not a historical revision ledger)."""

    kind: Literal["added_by_user"] = "added_by_user"
    actor: Annotated[str, Field(min_length=1)]
    at: datetime


class ChangedByUserProvenance(ExtractionReviewModel):
    """Latest effective change provenance retained on the current finding."""

    kind: Literal["changed_by_user"] = "changed_by_user"
    actor: Annotated[str, Field(min_length=1)]
    at: datetime


class RemovedByUserProvenance(ExtractionReviewModel):
    """Removal is an edit tombstone in the current state, not an approval/rejection."""

    kind: Literal["removed_by_user"] = "removed_by_user"
    actor: Annotated[str, Field(min_length=1)]
    at: datetime
    note: Annotated[str, Field(max_length=MAX_EDIT_NOTE_LENGTH)] | None = None


class FindingEvidenceStatus(StrEnum):
    DOCUMENT_EVIDENCE = "document_evidence"
    NO_DOCUMENT_EVIDENCE = "no_document_evidence"


class AssignedPage(ExtractionReviewModel):
    kind: Literal["assigned"] = "assigned"
    page_number: Annotated[int, Field(ge=1)]


class UnassignedPage(ExtractionReviewModel):
    kind: Literal["unassigned"] = "unassigned"


PageAssignment = Annotated[AssignedPage | UnassignedPage, Field(discriminator="kind")]


class UserFacingFinding(ExtractionReviewModel):
    """User-facing finding values.

    Page assignment is independent of exact document evidence: a finding may be
    page-assigned or unassigned with ``no_document_evidence``. Exact span/block/candidate
    claims remain separate and must not be invented.
    """

    component: Component
    display_text: Annotated[str, Field(min_length=1, max_length=MAX_FINDING_DISPLAY_TEXT)]
    page_assignment: PageAssignment
    evidence_status: FindingEvidenceStatus


class ReviewFindingRecord(ExtractionReviewModel):
    """One finding in the current complete list, including optional removal tombstone."""

    finding_id: Annotated[str, Field(min_length=1)]
    origin: FindingOrigin
    current: UserFacingFinding | None = None
    removed: Annotated[bool, Field(strict=True)] = False
    added_by_user: AddedByUserProvenance | None = None
    changed_by_user: ChangedByUserProvenance | None = None
    removed_by_user: RemovedByUserProvenance | None = None

    @model_validator(mode="after")
    def origin_current_agree(self) -> Self:
        if isinstance(self.origin, UserAddedFindingOrigin):
            if self.added_by_user is None:
                raise ValueError("user_added findings require added_by_user provenance")
            if (
                self.current is not None
                and self.current.evidence_status is FindingEvidenceStatus.DOCUMENT_EVIDENCE
            ):
                raise ValueError("user_added findings cannot claim document_evidence")
        elif self.added_by_user is not None:
            raise ValueError("lexical findings cannot carry added_by_user provenance")
        if self.removed:
            if self.current is None:
                raise ValueError("removed findings require current content for restore")
            if self.removed_by_user is None:
                raise ValueError("removed findings require removed_by_user provenance")
        else:
            if self.current is None:
                raise ValueError("active findings require current content")
            if self.removed_by_user is not None:
                raise ValueError("active findings cannot carry removed_by_user provenance")
        current = self.current
        assert current is not None
        if current.evidence_status is FindingEvidenceStatus.DOCUMENT_EVIDENCE and isinstance(
            self.origin, LexicalFindingOrigin
        ):
            evidence = self.origin.evidence
            if evidence.location is None or evidence.block_node_id is None:
                raise ValueError("document_evidence requires supplied lexical source evidence")
        return self

    @property
    def is_active(self) -> bool:
        return not self.removed


class ExtractionResultApproval(ExtractionReviewModel):
    """Current approval of the exact saved revision id (not an approval history ledger)."""

    actor: Annotated[str, Field(min_length=1)]
    at: datetime
    approved_revision_id: RevisionId


class ExtractionReviewState(ExtractionReviewModel):
    """One current Stage 3 review result. Earlier saves/approvals are discarded on replace."""

    schema_version: Literal["batchlens.extraction-review.v1"] = CONTRACT_SCHEMA_VERSION
    binding: WorkspaceBinding
    current_revision_id: RevisionId
    findings: tuple[ReviewFindingRecord, ...] = Field(max_length=MAX_FINDINGS_PER_REVIEW)
    approval: ExtractionResultApproval | None = None

    @model_validator(mode="after")
    def state_integrity(self) -> Self:
        _assert_unique_finding_ids(self.findings)
        if self.approval is not None:
            if self.approval.approved_revision_id != self.current_revision_id:
                raise ValueError("approval must name the current saved revision id")
        return self

    @property
    def approval_state(self) -> ReviewApprovalState:
        if self.approval is None:
            return ReviewApprovalState.NOT_APPROVED
        return ReviewApprovalState.APPROVED

    @property
    def job_id(self) -> str:
        return self.binding.document_source.job_id

    @property
    def run_id(self) -> str:
        return self.binding.run.run.run_id


class TransitionOutcomeKind(StrEnum):
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    CONFLICT = "conflict"
    VALIDATION_ERROR = "validation_error"


class InitializeReviewCommand(ExtractionReviewModel):
    revision_id: RevisionId
    actor: Annotated[str, Field(min_length=1)]
    created_at: datetime
    document_source: DocumentSourceReference
    run: ExtractionRunReference
    extraction: ExtractionOutcomeRecord
    findings: tuple[ReviewFindingRecord, ...] = Field(
        default_factory=tuple,
        max_length=MAX_FINDINGS_PER_REVIEW,
    )


class InitializeReviewResult(ExtractionReviewModel):
    outcome: Literal["initialized"] = "initialized"
    state: ExtractionReviewState


class FindingEditOp(ExtractionReviewModel):
    finding_id: Annotated[str, Field(min_length=1)]


class AddFindingEdit(FindingEditOp):
    """Add a user finding. finding_id must be unique in the current complete list."""

    op: Literal["add"] = "add"
    component: Component
    display_text: Annotated[str, Field(min_length=1, max_length=MAX_FINDING_DISPLAY_TEXT)]
    page_assignment: PageAssignment
    evidence_status: FindingEvidenceStatus


class ReplaceFindingEdit(FindingEditOp):
    op: Literal["replace"] = "replace"
    current: UserFacingFinding


class PatchFindingTextEdit(FindingEditOp):
    op: Literal["patch_text"] = "patch_text"
    display_text: Annotated[str, Field(min_length=1, max_length=MAX_FINDING_DISPLAY_TEXT)]


class RemoveFindingEdit(FindingEditOp):
    op: Literal["remove"] = "remove"
    note: Annotated[str, Field(max_length=MAX_EDIT_NOTE_LENGTH)] | None = None


class RestoreFindingEdit(FindingEditOp):
    """Restore a removed tombstone to active in the current state (not a history undo)."""

    op: Literal["restore"] = "restore"


FindingEditCommand = Annotated[
    AddFindingEdit
    | ReplaceFindingEdit
    | PatchFindingTextEdit
    | RemoveFindingEdit
    | RestoreFindingEdit,
    Field(discriminator="op"),
]


class SaveReviewEditsCommand(ExtractionReviewModel):
    expected_revision_id: RevisionId
    actor: Annotated[str, Field(min_length=1)]
    at: datetime
    edits: tuple[FindingEditCommand, ...] = Field(max_length=MAX_FINDING_EDITS_PER_SAVE)

    @model_validator(mode="after")
    def edits_are_unique(self) -> Self:
        seen: set[str] = set()
        for edit in self.edits:
            if edit.finding_id in seen:
                raise ValueError("duplicate finding_id in one save batch")
            seen.add(edit.finding_id)
        return self


class SaveReviewEditsResult(ExtractionReviewModel):
    outcome: TransitionOutcomeKind
    state: ExtractionReviewState | None = None
    message: Annotated[str, Field(min_length=1)] | None = None


class ApproveExtractionResultCommand(ExtractionReviewModel):
    expected_revision_id: RevisionId
    actor: Annotated[str, Field(min_length=1)]
    at: datetime
    target_revision_id: RevisionId


class ApproveExtractionResultResult(ExtractionReviewModel):
    outcome: TransitionOutcomeKind
    state: ExtractionReviewState | None = None
    approval: ExtractionResultApproval | None = None
    message: Annotated[str, Field(min_length=1)] | None = None


def has_usable_completed_component(extraction: ExtractionOutcomeRecord) -> bool:
    """True when at least one component completed (including completed zero-hit)."""

    return any(item.outcome is ExtractionOutcome.COMPLETED for item in extraction.components)


def is_reviewable_publication(run: ExtractionRunReference) -> bool:
    return (
        run.publication.status is PublicationStatus.COMPLETED
        and run.publication.final_manifest is not None
        and run.published_manifest is not None
    )


def _assert_unique_finding_ids(findings: tuple[ReviewFindingRecord, ...]) -> None:
    if len({finding.finding_id for finding in findings}) != len(findings):
        raise ValueError("finding_id values must be unique")

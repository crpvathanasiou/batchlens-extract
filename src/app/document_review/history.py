"""Derived in-memory projection of a frozen committed review chain.

B1 is not a record store. The published ``ReviewHead`` and immutable
``ReviewRevision`` envelopes remain authoritative. This module never writes
``history.jsonl``, never publishes a head, and does not verify source/raw/export
bytes beyond the revision envelopes already read to validate the chain.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import ValidationError

from app.document_conversion.aws import S3Source
from app.document_conversion.contracts import Reference
from app.document_jobs.contracts import Artifact, Job
from app.document_review.contracts import (
    CommittedAction,
    DecisionAction,
    PageApproval,
    ReviewError,
    ReviewHead,
    ReviewModel,
    ReviewRevision,
    RevisionId,
    TextChange,
)
from app.document_review.mapping import document_hash, page_hash
from app.document_review.operations import load_committed_chain

HISTORY_PROJECTION_SCHEMA = "batchlens.committed-history.projection.v1"
ProjectedOrigin = Literal["MANUAL_EDIT", "APPLIED_SUGGESTION", "UNKNOWN"]
EvidenceState = Literal["not_verified"]


class HistoryEvidenceLimits(ReviewModel):
    """B1 verifies committed revision envelopes only."""

    committed_revision_envelopes: Literal["verified"] = "verified"
    source_pdf_bytes: EvidenceState = "not_verified"
    raw_ocr_bytes: EvidenceState = "not_verified"
    baseline_bytes: EvidenceState = "not_verified"
    export_bytes: EvidenceState = "not_verified"


class HistoryCoverage(ReviewModel):
    """Coverage of one frozen published head. Not proof that supporting blobs exist."""

    schema_name: Literal["batchlens.committed-history.projection.v1"] = HISTORY_PROJECTION_SCHEMA
    schema_version: Literal[1] = 1
    head_revision_id: RevisionId
    head_generation: int
    complete_through_revision_id: RevisionId
    complete_through_generation: int
    projected_revision_count: int
    evidence_limits: HistoryEvidenceLimits = HistoryEvidenceLimits()


class HistoryInputs(ReviewModel):
    """Canonical conversion identity copied from the authoritative committed envelopes."""

    baseline: Artifact
    accepted_source: S3Source
    raw: Artifact


class HistoryTextChange(ReviewModel):
    node_id: str
    page_number: int
    path: str
    source_references: tuple[Reference, ...]
    original_text: str
    previous_text: str
    new_text: str
    actor: str
    at: datetime
    revision_id: RevisionId
    origin: ProjectedOrigin
    finding_id: str | None = None


class HistoryFindingDecision(ReviewModel):
    finding_id: str
    code: str
    action: DecisionAction
    note: str | None
    actor: str
    at: datetime
    revision_id: RevisionId
    recorded_region_hash: str
    finding_region_hash: str
    region_hash_matches: bool


class HistoryPageApprovalGrant(ReviewModel):
    page_number: int
    content_hash: str
    actor: str
    at: datetime
    granted_revision_id: RevisionId


class HistoryPageApprovalInvalidation(ReviewModel):
    """Derived when a prior page approval is absent in the next snapshot.

    A replacement grant (repeated Approve page) is not an invalidation.
    """

    kind: Literal["DERIVED_OUTCOME"] = "DERIVED_OUTCOME"
    page_number: int
    prior_approval: HistoryPageApprovalGrant
    prior_revision_id: RevisionId
    invalidated_by_revision_id: RevisionId


class HistoryDocumentApprovalGrant(ReviewModel):
    granted_revision_id: RevisionId
    document_hash: str
    actor: str
    at: datetime


class HistoryDocumentApprovalInvalidation(ReviewModel):
    """Derived when a prior document approval is absent in the next snapshot.

    A replacement grant (repeated Approve & Export) is not an invalidation.
    """

    kind: Literal["DERIVED_OUTCOME"] = "DERIVED_OUTCOME"
    prior_approval: HistoryDocumentApprovalGrant
    prior_revision_id: RevisionId
    invalidated_by_revision_id: RevisionId


class HistoryExportPointers(ReviewModel):
    """Stored export artifact references. Bytes are not read or verified here."""

    approving_revision_id: RevisionId
    html_artifact: Artifact
    json_artifact: Artifact


class HistoryRevisionRecord(ReviewModel):
    """One committed revision. Order is generation and parent links, not timestamps.

    ``revision_created_at`` is envelope ``created_at`` (server time before CAS publish).
    """

    kind: Literal["COMMITTED_TRANSITION"] = "COMMITTED_TRANSITION"
    revision_id: RevisionId
    parent_revision_id: RevisionId | None
    generation: int
    action: CommittedAction
    revision_created_at: datetime
    actor: str
    envelope_schema_version: str
    revision_artifact: Artifact
    changes: tuple[HistoryTextChange, ...] = ()
    finding_decisions: tuple[HistoryFindingDecision, ...] = ()
    page_approvals_granted: tuple[HistoryPageApprovalGrant, ...] = ()
    document_approval_granted: HistoryDocumentApprovalGrant | None = None
    exports: HistoryExportPointers | None = None
    page_approvals_invalidated: tuple[HistoryPageApprovalInvalidation, ...] = ()
    document_approval_invalidated: HistoryDocumentApprovalInvalidation | None = None


class CommittedHistoryProjection(ReviewModel):
    coverage: HistoryCoverage
    inputs: HistoryInputs
    records: tuple[HistoryRevisionRecord, ...]


def project_committed_history(
    job: Job,
    head: ReviewHead,
    read_revision: Callable[[Artifact], ReviewRevision],
) -> CommittedHistoryProjection:
    """Project the complete published parent chain of one frozen head.

    ``read_revision`` must return the envelope for an artifact reference. Missing,
    malformed, or invariant-breaking input raises ``INVALID_REVIEW_STATE`` and
    does not return a partial projection marked complete.

    Causal order is generation plus validated parent links. Envelope
    ``created_at`` (projected as ``revision_created_at``) is server revision
    creation time before conditional head publication, not the publication instant.
    The supplied head's status, document approval, and export pointers must equal
    the top revision it points to.
    """

    reader = _bound_reader(read_revision)
    head_revision = reader(head.revision)
    _check_frozen_head(job, head, head_revision)
    newest_first = load_committed_chain(job, head_revision, reader)
    artifacts = _revision_artifacts(head, newest_first)
    chronological = tuple(reversed(newest_first))
    records = tuple(
        _record(
            revision,
            artifacts[revision.revision_id],
            previous=chronological[index - 1] if index else None,
        )
        for index, revision in enumerate(chronological)
    )
    return CommittedHistoryProjection(
        coverage=HistoryCoverage(
            head_revision_id=head.revision_id,
            head_generation=head.generation,
            complete_through_revision_id=head.revision_id,
            complete_through_generation=head.generation,
            projected_revision_count=len(records),
        ),
        inputs=HistoryInputs(
            baseline=head_revision.baseline,
            accepted_source=head_revision.accepted_source,
            raw=head_revision.raw,
        ),
        records=records,
    )


def _bound_reader(
    read_revision: Callable[[Artifact], ReviewRevision],
) -> Callable[[Artifact], ReviewRevision]:
    def read(artifact: Artifact) -> ReviewRevision:
        try:
            return read_revision(artifact)
        except ReviewError:
            raise
        except (ValidationError, ValueError, TypeError, UnicodeDecodeError, KeyError, OSError):
            raise ReviewError("INVALID_REVIEW_STATE") from None

    return read


def _check_frozen_head(job: Job, head: ReviewHead, revision: ReviewRevision) -> None:
    """Reject a head whose identity or summary fields disagree with its top envelope."""

    try:
        baseline = job.artifacts["document.json"]
    except KeyError:
        raise ReviewError("INVALID_REVIEW_STATE") from None
    if (
        head.job_id != job.id
        or head.owner != job.owner
        or head.baseline != baseline
        or head.accepted_source != job.source
        or head.raw != job.raw
        or revision.revision_id != head.revision_id
        or revision.generation != head.generation
        or revision.job_id != job.id
        or revision.owner != job.owner
        or revision.baseline != head.baseline
        or revision.accepted_source != head.accepted_source
        or revision.raw != head.raw
        or revision.status != head.status
        or revision.document_approval != head.document_approval
        or revision.exports != head.exports
    ):
        raise ReviewError("INVALID_REVIEW_STATE")


def _revision_artifacts(
    head: ReviewHead, newest_first: tuple[ReviewRevision, ...]
) -> dict[str, Artifact]:
    artifacts = {newest_first[0].revision_id: head.revision}
    for child in newest_first:
        if child.parent_revision_id is None:
            continue
        if child.parent is None:
            raise ReviewError("INVALID_REVIEW_STATE")
        artifacts[child.parent_revision_id] = child.parent
    if any(revision.revision_id not in artifacts for revision in newest_first):
        raise ReviewError("INVALID_REVIEW_STATE")
    return artifacts


def _record(
    revision: ReviewRevision,
    artifact: Artifact,
    *,
    previous: ReviewRevision | None,
) -> HistoryRevisionRecord:
    _check_action_invariants(revision)
    page_invalidations, document_invalidation = _derived_invalidations(previous, revision)
    exports = None
    if revision.exports is not None:
        exports = HistoryExportPointers(
            approving_revision_id=revision.revision_id,
            html_artifact=revision.exports.html_artifact,
            json_artifact=revision.exports.json_artifact,
        )
    document_grant = None
    if (
        revision.document_approval is not None
        and revision.document_approval.revision_id == revision.revision_id
    ):
        document_grant = HistoryDocumentApprovalGrant(
            granted_revision_id=revision.document_approval.revision_id,
            document_hash=revision.document_approval.document_hash,
            actor=revision.document_approval.actor,
            at=revision.document_approval.at,
        )
    return HistoryRevisionRecord(
        revision_id=revision.revision_id,
        parent_revision_id=revision.parent_revision_id,
        generation=revision.generation,
        action=revision.action,
        revision_created_at=revision.created_at,
        actor=revision.actor,
        envelope_schema_version=revision.schema_version,
        revision_artifact=artifact,
        changes=_changes(revision),
        finding_decisions=_decisions_made_here(revision),
        page_approvals_granted=_page_grants(revision),
        document_approval_granted=document_grant,
        exports=exports,
        page_approvals_invalidated=page_invalidations,
        document_approval_invalidated=document_invalidation,
    )


def _check_action_invariants(revision: ReviewRevision) -> None:
    _check_page_approvals(revision)
    _check_document_approval_and_exports(revision)
    if revision.action == "PAGE_APPROVED" and not any(
        page.approval is not None and page.approval.revision_id == revision.revision_id
        for page in revision.pages
    ):
        raise ReviewError("INVALID_REVIEW_STATE")


def _check_page_approvals(revision: ReviewRevision) -> None:
    for page in revision.pages:
        approval = page.approval
        if approval is None:
            continue
        try:
            expected_hash = page_hash(revision.document, page.page_number)
        except ReviewError:
            raise ReviewError("INVALID_REVIEW_STATE") from None
        if approval.content_hash != page.content_hash or page.content_hash != expected_hash:
            raise ReviewError("INVALID_REVIEW_STATE")
        if approval.revision_id == revision.revision_id and revision.action != "PAGE_APPROVED":
            raise ReviewError("INVALID_REVIEW_STATE")


def _check_document_approval_and_exports(revision: ReviewRevision) -> None:
    approval = revision.document_approval
    if revision.action == "DOCUMENT_APPROVED":
        if (
            approval is None
            or approval.revision_id != revision.revision_id
            or approval.document_hash != document_hash(revision.document)
            or revision.exports is None
        ):
            raise ReviewError("INVALID_REVIEW_STATE")
        return
    if approval is not None or revision.exports is not None:
        raise ReviewError("INVALID_REVIEW_STATE")


def _changes(revision: ReviewRevision) -> tuple[HistoryTextChange, ...]:
    nodes = {node.node_id: node for node in revision.catalogue.nodes}
    findings = {finding.finding_id: finding for finding in revision.findings}
    projected: list[HistoryTextChange] = []
    for change in revision.changes:
        node = nodes.get(change.node_id)
        if node is None or change.revision_id != revision.revision_id:
            raise ReviewError("INVALID_REVIEW_STATE")
        origin = _origin(change)
        if origin == "APPLIED_SUGGESTION":
            finding = findings.get(change.finding_id) if change.finding_id is not None else None
            if (
                finding is None
                or finding.decision is None
                or finding.decision.revision_id != revision.revision_id
            ):
                raise ReviewError("INVALID_REVIEW_STATE")
        projected.append(
            HistoryTextChange(
                node_id=change.node_id,
                page_number=node.page_number,
                path=node.path,
                source_references=node.references,
                original_text=change.original_text,
                previous_text=change.previous_text,
                new_text=change.new_text,
                actor=change.actor,
                at=change.at,
                revision_id=change.revision_id,
                origin=origin,
                finding_id=change.finding_id,
            )
        )
    return tuple(projected)


def _origin(change: TextChange) -> ProjectedOrigin:
    if change.origin is None:
        return "UNKNOWN"
    return change.origin


def _decisions_made_here(revision: ReviewRevision) -> tuple[HistoryFindingDecision, ...]:
    decisions: list[HistoryFindingDecision] = []
    for finding in revision.findings:
        decision = finding.decision
        if decision is None or decision.revision_id != revision.revision_id:
            continue
        decisions.append(
            HistoryFindingDecision(
                finding_id=finding.finding_id,
                code=finding.code,
                action=decision.action,
                note=decision.note,
                actor=decision.actor,
                at=decision.at,
                revision_id=decision.revision_id,
                recorded_region_hash=decision.region_hash,
                finding_region_hash=finding.region_hash,
                region_hash_matches=decision.region_hash == finding.region_hash,
            )
        )
    return tuple(decisions)


def _page_grants(revision: ReviewRevision) -> tuple[HistoryPageApprovalGrant, ...]:
    return tuple(
        HistoryPageApprovalGrant(
            page_number=page.page_number,
            content_hash=page.approval.content_hash,
            actor=page.approval.actor,
            at=page.approval.at,
            granted_revision_id=page.approval.revision_id,
        )
        for page in revision.pages
        if page.approval is not None and page.approval.revision_id == revision.revision_id
    )


def _grant_from_page(page_number: int, approval: PageApproval) -> HistoryPageApprovalGrant:
    return HistoryPageApprovalGrant(
        page_number=page_number,
        content_hash=approval.content_hash,
        actor=approval.actor,
        at=approval.at,
        granted_revision_id=approval.revision_id,
    )


def _derived_invalidations(
    previous: ReviewRevision | None, current: ReviewRevision
) -> tuple[tuple[HistoryPageApprovalInvalidation, ...], HistoryDocumentApprovalInvalidation | None]:
    if previous is None:
        return (), None
    previous_pages = {page.page_number: page for page in previous.pages}
    current_pages = {page.page_number: page for page in current.pages}
    if set(previous_pages) != set(current_pages):
        raise ReviewError("INVALID_REVIEW_STATE")
    invalidated: list[HistoryPageApprovalInvalidation] = []
    for number, prior_page in previous_pages.items():
        current_page = current_pages[number]
        prior = prior_page.approval
        if prior is None or current_page.approval is not None:
            continue
        invalidated.append(
            HistoryPageApprovalInvalidation(
                page_number=number,
                prior_approval=_grant_from_page(number, prior),
                prior_revision_id=previous.revision_id,
                invalidated_by_revision_id=current.revision_id,
            )
        )
    document_invalidation = None
    prior_document = previous.document_approval
    current_document = current.document_approval
    if prior_document is not None and current_document is None:
        document_invalidation = HistoryDocumentApprovalInvalidation(
            prior_approval=HistoryDocumentApprovalGrant(
                granted_revision_id=prior_document.revision_id,
                document_hash=prior_document.document_hash,
                actor=prior_document.actor,
                at=prior_document.at,
            ),
            prior_revision_id=previous.revision_id,
            invalidated_by_revision_id=current.revision_id,
        )
    return tuple(invalidated), document_invalidation

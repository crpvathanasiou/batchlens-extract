"""Fail-closed in-memory committed-history projection (B1)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import cast

import pytest

from app.document_jobs.contracts import Artifact
from app.document_review.contracts import (
    FinalApprovalBody,
    FindingDecisionRequest,
    PageApprovalBody,
    RequestedChange,
    ReviewError,
    ReviewHead,
    ReviewRevision,
    ReviewState,
    UpdateReviewBody,
)
from app.document_review.history import CommittedHistoryProjection, project_committed_history
from app.document_review.service import ReviewService
from tests.document_review.test_backend_review import IDS, Heads, Objects, make_service


def _page_node(state: ReviewState, page_number: int):
    return next(node for node in state.catalogue.nodes if node.page_number == page_number)


def _manual_body(
    state: ReviewState,
    text: str = "page two corrected",
    *,
    expected_revision: str | None = None,
) -> UpdateReviewBody:
    return UpdateReviewBody(
        expected_revision=expected_revision,
        changes=(RequestedChange(node_id=_page_node(state, 2).node_id, text=text),),
    )


def _suggestion_body(
    state: ReviewState, *, expected_revision: str | None = None
) -> UpdateReviewBody:
    finding = state.findings[0]
    suggestion = finding.suggested_replacement
    assert suggestion is not None
    return UpdateReviewBody(
        expected_revision=expected_revision,
        decisions=(
            FindingDecisionRequest(
                finding_id=finding.finding_id,
                action="RESOLVED_AFTER_EDIT",
                replacement=RequestedChange(node_id=suggestion.node_id, text=suggestion.text),
                expected_region_hash=finding.region_hash,
            ),
        ),
    )


def _strip_legacy(payload: dict[str, object]) -> bytes:
    payload["schema_version"] = "1.0.0"
    payload.pop("save_operation", None)
    for change in cast(list[dict[str, object]], payload.get("changes", [])):
        change.pop("origin", None)
        change.pop("finding_id", None)
    return json.dumps(payload, ensure_ascii=False).encode()


def _reader(objects: Objects) -> Callable[[Artifact], ReviewRevision]:
    def read(artifact: Artifact) -> ReviewRevision:
        return ReviewRevision.model_validate_json(objects.read(artifact))

    return read


def _project(service: ReviewService, heads: Heads, objects: Objects) -> CommittedHistoryProjection:
    job = service.jobs.get("job")
    assert job is not None and heads.head is not None
    return project_committed_history(job, heads.head, _reader(objects))


def _corrupt(
    objects: Objects, artifact: Artifact, mutate: Callable[[dict[str, object]], None]
) -> None:
    payload = json.loads(objects.read(artifact))
    mutate(payload)
    objects.data[(artifact.key, artifact.version)] = json.dumps(payload).encode()


def test_projects_chronological_records_and_coverage_through_head() -> None:
    service, heads, objects = make_service(warnings=False)
    initial = service.get("job", "alice")
    first = service.update("job", "alice", _manual_body(initial))
    second = service.update(
        "job",
        "alice",
        _manual_body(first, "later edit", expected_revision=first.revision_id),
    )
    approved = service.approve_page(
        "job", "alice", 1, PageApprovalBody(expected_revision=cast(str, second.revision_id))
    )
    projection = _project(service, heads, objects)
    head = cast(ReviewHead, heads.head)
    assert projection.coverage.head_revision_id == approved.revision_id == head.revision_id
    assert projection.coverage.head_generation == 3
    assert projection.coverage.complete_through_revision_id == approved.revision_id
    assert projection.coverage.complete_through_generation == 3
    assert projection.coverage.projected_revision_count == 3
    assert projection.coverage.evidence_limits.export_bytes == "not_verified"
    assert projection.inputs.baseline == head.baseline
    assert projection.inputs.raw == head.raw
    assert projection.inputs.accepted_source == head.accepted_source
    records = projection.records
    assert [record.generation for record in records] == [1, 2, 3]
    assert [record.parent_revision_id for record in records] == [
        None,
        first.revision_id,
        second.revision_id,
    ]
    created = cast(ReviewRevision, first.revision).created_at
    assert {record.revision_created_at for record in records} == {created}
    assert [record.action for record in records] == [
        "DRAFT_SAVED",
        "DRAFT_SAVED",
        "PAGE_APPROVED",
    ]
    assert [record.kind for record in records] == ["COMMITTED_TRANSITION"] * 3
    assert records[2].revision_artifact == head.revision
    assert records[0].revision_artifact == cast(ReviewRevision, second.revision).parent
    assert records[1].revision_artifact == cast(ReviewRevision, approved.revision).parent


def test_unpublished_candidate_is_excluded() -> None:
    service, heads, objects = make_service(warnings=False)
    initial = service.get("job", "alice")
    saved = service.update("job", "alice", _manual_body(initial))
    objects.put_revision("job", IDS[10], b'{"not":"committed"}')
    projection = _project(service, heads, objects)
    assert projection.coverage.projected_revision_count == 1
    assert projection.records[0].revision_id == saved.revision_id
    assert IDS[10] not in {record.revision_id for record in projection.records}


def test_text_provenance_manual_applied_and_legacy_unknown() -> None:
    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    legacy = service.update("job", "alice", _manual_body(initial))
    artifact = cast(ReviewHead, heads.head).revision
    objects.data[(artifact.key, artifact.version)] = _strip_legacy(
        json.loads(objects.read(artifact))
    )
    applied = service.update(
        "job",
        "alice",
        _suggestion_body(service.get("job", "alice"), expected_revision=legacy.revision_id),
    )
    node = next(item for item in applied.catalogue.nodes if item.page_number == 2)
    manual = service.update(
        "job",
        "alice",
        UpdateReviewBody(
            expected_revision=applied.revision_id,
            changes=(RequestedChange(node_id=node.node_id, text="manual again"),),
        ),
    )
    projection = _project(service, heads, objects)
    origins = [change.origin for record in projection.records for change in record.changes]
    assert origins == ["UNKNOWN", "APPLIED_SUGGESTION", "MANUAL_EDIT"]
    unknown, suggestion, edited = (
        change for record in projection.records for change in record.changes
    )
    assert unknown.finding_id is None
    assert unknown.page_number == 2
    assert unknown.path == "pages[2].elements[0]"
    assert suggestion.origin == "APPLIED_SUGGESTION"
    assert suggestion.finding_id == initial.findings[0].finding_id
    assert suggestion.page_number == 1
    assert suggestion.source_references
    assert edited.origin == "MANUAL_EDIT"
    assert edited.finding_id is None
    assert edited.new_text == "manual again"
    assert edited.revision_id == manual.revision_id
    assert projection.records[0].envelope_schema_version == "1.0.0"
    assert projection.records[1].envelope_schema_version == "1.1.0"


def test_copied_decisions_approvals_not_duplicated_and_invalidation_is_derived() -> None:
    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    finding_id = initial.findings[0].finding_id
    acknowledged = service.update(
        "job",
        "alice",
        UpdateReviewBody(
            decisions=(
                FindingDecisionRequest(finding_id=finding_id, action="ACKNOWLEDGED_LIMITATION"),
            )
        ),
    )
    page1 = service.approve_page(
        "job", "alice", 1, PageApprovalBody(expected_revision=cast(str, acknowledged.revision_id))
    )
    page2 = service.approve_page(
        "job", "alice", 2, PageApprovalBody(expected_revision=cast(str, page1.revision_id))
    )
    node = next(item for item in page2.catalogue.nodes if item.page_number == 1)
    edited = service.update(
        "job",
        "alice",
        UpdateReviewBody(
            expected_revision=page2.revision_id,
            changes=(RequestedChange(node_id=node.node_id, text="page one edited"),),
        ),
    )
    projection = _project(service, heads, objects)
    decision_revisions = [
        decision.revision_id
        for record in projection.records
        for decision in record.finding_decisions
    ]
    assert decision_revisions == [acknowledged.revision_id]
    first_decision = projection.records[0].finding_decisions[0]
    assert first_decision.finding_id == finding_id
    assert first_decision.action == "ACKNOWLEDGED_LIMITATION"
    assert first_decision.region_hash_matches is True
    assert projection.records[1].finding_decisions == ()
    assert projection.records[2].finding_decisions == ()
    grants = [
        (record.revision_id, grant.page_number)
        for record in projection.records
        for grant in record.page_approvals_granted
    ]
    assert grants == [(page1.revision_id, 1), (page2.revision_id, 2)]
    assert projection.records[3].page_approvals_granted == ()
    invalidated = projection.records[3].page_approvals_invalidated
    assert len(invalidated) == 1
    event = invalidated[0]
    assert event.kind == "DERIVED_OUTCOME"
    assert event.page_number == 1
    assert event.prior_approval.granted_revision_id == page1.revision_id
    assert event.prior_revision_id == page2.revision_id
    assert event.invalidated_by_revision_id == edited.revision_id
    assert projection.records[3].document_approval_invalidated is None


def test_document_approved_reports_stored_export_pointers() -> None:
    service, heads, objects = make_service(warnings=False)
    initial = service.get("job", "alice")
    saved = service.update("job", "alice", _manual_body(initial))
    page1 = service.approve_page(
        "job", "alice", 1, PageApprovalBody(expected_revision=cast(str, saved.revision_id))
    )
    page2 = service.approve_page(
        "job", "alice", 2, PageApprovalBody(expected_revision=cast(str, page1.revision_id))
    )
    approved = service.approve(
        "job", "alice", FinalApprovalBody(expected_revision=cast(str, page2.revision_id))
    )
    projection = _project(service, heads, objects)
    record = projection.records[-1]
    assert record.action == "DOCUMENT_APPROVED"
    assert record.revision_id == approved.revision_id
    assert record.document_approval_granted is not None
    assert record.document_approval_granted.granted_revision_id == approved.revision_id
    assert record.exports is not None
    assert record.exports.approving_revision_id == approved.revision_id
    stored = cast(ReviewRevision, approved.revision).exports
    assert stored is not None
    assert record.exports.html_artifact == stored.html_artifact
    assert record.exports.json_artifact == stored.json_artifact
    assert projection.coverage.evidence_limits.export_bytes == "not_verified"

    node = next(item for item in approved.catalogue.nodes if item.page_number == 1)
    service.update(
        "job",
        "alice",
        UpdateReviewBody(
            expected_revision=approved.revision_id,
            changes=(RequestedChange(node_id=node.node_id, text="reopened"),),
        ),
    )
    reopened = _project(service, heads, objects)
    derived = reopened.records[-1].document_approval_invalidated
    assert derived is not None
    assert derived.kind == "DERIVED_OUTCOME"
    assert derived.prior_approval.granted_revision_id == approved.revision_id
    assert derived.invalidated_by_revision_id == reopened.records[-1].revision_id
    assert reopened.records[-1].exports is None


@pytest.mark.parametrize("mode", ["missing", "corrupt", "cyclic", "wrong_context"])
def test_broken_chain_fails_closed_without_partial_projection(mode: str) -> None:
    service, heads, objects = make_service(warnings=False)
    initial = service.get("job", "alice")
    first = service.update("job", "alice", _manual_body(initial))
    second = service.update(
        "job",
        "alice",
        _manual_body(first, "later", expected_revision=first.revision_id),
    )
    parent = cast(ReviewRevision, second.revision).parent
    assert parent is not None
    if mode == "missing":
        objects.data.pop((parent.key, parent.version))
    elif mode == "corrupt":
        objects.data[(parent.key, parent.version)] = b"{"
    elif mode == "cyclic":
        head_artifact = cast(ReviewHead, heads.head).revision
        head_payload = json.loads(objects.read(head_artifact))
        head_payload["parent_revision_id"] = second.revision_id
        objects.data[(head_artifact.key, head_artifact.version)] = json.dumps(head_payload).encode()
        payload = json.loads(objects.read(parent))
        payload["revision_id"] = second.revision_id
        payload["generation"] = 1
        payload["parent_revision_id"] = None
        payload["parent"] = None
        objects.data[(parent.key, parent.version)] = json.dumps(payload).encode()
    else:
        payload = json.loads(objects.read(parent))
        payload["job_id"] = "other-job"
        objects.data[(parent.key, parent.version)] = json.dumps(payload).encode()
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        _project(service, heads, objects)


def test_inconsistent_change_catalogue_relationship_fails_closed() -> None:
    service, heads, objects = make_service(warnings=False)
    initial = service.get("job", "alice")
    saved = service.update("job", "alice", _manual_body(initial))
    artifact = cast(ReviewHead, heads.head).revision

    def rename(payload: dict[str, object]) -> None:
        changes = cast(list[dict[str, object]], payload["changes"])
        changes[0]["node_id"] = "node_missing_from_catalogue"

    _corrupt(objects, artifact, rename)
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        _project(service, heads, objects)
    assert saved.revision_id == cast(ReviewHead, heads.head).revision_id


def _approve_document(service: ReviewService) -> ReviewState:
    initial = service.get("job", "alice")
    saved = service.update("job", "alice", _manual_body(initial))
    page1 = service.approve_page(
        "job", "alice", 1, PageApprovalBody(expected_revision=cast(str, saved.revision_id))
    )
    page2 = service.approve_page(
        "job", "alice", 2, PageApprovalBody(expected_revision=cast(str, page1.revision_id))
    )
    return service.approve(
        "job", "alice", FinalApprovalBody(expected_revision=cast(str, page2.revision_id))
    )


@pytest.mark.parametrize("field", ["document_approval", "exports"])
def test_document_approved_missing_approval_or_exports_fails_closed(field: str) -> None:
    service, heads, objects = make_service(warnings=False)
    approved = _approve_document(service)
    artifact = cast(ReviewHead, heads.head).revision

    def drop(payload: dict[str, object]) -> None:
        payload[field] = None

    _corrupt(objects, artifact, drop)
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        _project(service, heads, objects)
    assert approved.revision_id == cast(ReviewHead, heads.head).revision_id


def test_repeated_page_approval_is_later_grant_not_invalidation() -> None:
    service, heads, objects = make_service(warnings=False)
    initial = service.get("job", "alice")
    saved = service.update("job", "alice", _manual_body(initial))
    first = service.approve_page(
        "job", "alice", 1, PageApprovalBody(expected_revision=cast(str, saved.revision_id))
    )
    second = service.approve_page(
        "job", "alice", 1, PageApprovalBody(expected_revision=cast(str, first.revision_id))
    )
    projection = _project(service, heads, objects)
    last = projection.records[-1]
    assert last.action == "PAGE_APPROVED"
    assert last.revision_id == second.revision_id
    assert [grant.page_number for grant in last.page_approvals_granted] == [1]
    assert last.page_approvals_granted[0].granted_revision_id == second.revision_id
    assert last.page_approvals_invalidated == ()
    prior_grants = [
        grant.granted_revision_id
        for record in projection.records
        for grant in record.page_approvals_granted
    ]
    assert prior_grants == [first.revision_id, second.revision_id]


def test_repeated_document_approval_is_later_grant_not_invalidation() -> None:
    service, heads, objects = make_service(warnings=False)
    first = _approve_document(service)
    second = service.approve(
        "job", "alice", FinalApprovalBody(expected_revision=cast(str, first.revision_id))
    )
    projection = _project(service, heads, objects)
    last = projection.records[-1]
    assert last.action == "DOCUMENT_APPROVED"
    assert last.revision_id == second.revision_id
    assert last.document_approval_granted is not None
    assert last.document_approval_granted.granted_revision_id == second.revision_id
    assert last.document_approval_invalidated is None
    assert last.exports is not None
    assert last.exports.approving_revision_id == second.revision_id
    grants = [
        record.document_approval_granted.granted_revision_id
        for record in projection.records
        if record.document_approval_granted is not None
    ]
    assert grants == [first.revision_id, second.revision_id]


@pytest.mark.parametrize("target", ["page", "document"])
def test_corrupt_approval_hash_fails_closed(target: str) -> None:
    service, heads, objects = make_service(warnings=False)
    if target == "page":
        initial = service.get("job", "alice")
        saved = service.update("job", "alice", _manual_body(initial))
        service.approve_page(
            "job", "alice", 1, PageApprovalBody(expected_revision=cast(str, saved.revision_id))
        )

        def mutate(payload: dict[str, object]) -> None:
            pages = cast(list[dict[str, object]], payload["pages"])
            approval = cast(dict[str, object], pages[0]["approval"])
            approval["content_hash"] = "0" * 64
    else:
        _approve_document(service)

        def mutate(payload: dict[str, object]) -> None:
            approval = cast(dict[str, object], payload["document_approval"])
            approval["document_hash"] = "0" * 64

    artifact = cast(ReviewHead, heads.head).revision
    _corrupt(objects, artifact, mutate)
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        _project(service, heads, objects)


@pytest.mark.parametrize("field", ["status", "document_approval", "exports"])
def test_mismatched_frozen_head_summary_fails_closed(field: str) -> None:
    """Detects supplied ReviewHead/envelope disagreement. Does not read evidence bytes."""

    service, heads, objects = make_service(warnings=False)
    if field == "status":
        initial = service.get("job", "alice")
        service.update("job", "alice", _manual_body(initial))
        mismatched = cast(ReviewHead, heads.head).model_copy(update={"status": "APPROVED"})
    else:
        _approve_document(service)
        head = cast(ReviewHead, heads.head)
        if field == "document_approval":
            assert head.document_approval is not None
            mismatched = head.model_copy(
                update={
                    "document_approval": head.document_approval.model_copy(
                        update={"document_hash": "0" * 64}
                    )
                }
            )
        else:
            assert head.exports is not None
            mismatched = head.model_copy(
                update={
                    "exports": head.exports.model_copy(
                        update={
                            "html_artifact": head.exports.html_artifact.model_copy(
                                update={"version": "head-envelope-mismatch"}
                            )
                        }
                    )
                }
            )
    job = service.jobs.get("job")
    assert job is not None and heads.head is not None
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        project_committed_history(job, mismatched, _reader(objects))
    assert _project(service, heads, objects).coverage.head_revision_id == heads.head.revision_id

"""Save operation identity, fingerprinting, and committed-chain reconciliation."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from itertools import count
from threading import Barrier, Event, Lock
from typing import cast

import pytest
from pydantic import ValidationError

from app.document_jobs.contracts import Artifact, Job
from app.document_review.contracts import (
    FindingDecisionRequest,
    RequestedChange,
    ReviewError,
    ReviewHead,
    ReviewRevision,
    ReviewState,
    SaveReceipt,
    UpdateResult,
    UpdateReviewBody,
)
from app.document_review.operations import save_request_fingerprint
from app.document_review.service import ReviewService
from tests.document_review.test_backend_review import (
    BASELINE,
    IDS,
    RAW,
    SOURCE,
    Heads,
    Jobs,
    Objects,
    make_service,
    synthetic_document,
)

OP_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OP_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OP_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def _page_node(state: ReviewState, page_number: int):
    return next(node for node in state.catalogue.nodes if node.page_number == page_number)


def _manual_body(
    state: ReviewState,
    text: str = "page two corrected",
    *,
    expected_revision: str | None = None,
    operation_id: str | None = None,
) -> UpdateReviewBody:
    return UpdateReviewBody(
        expected_revision=expected_revision,
        changes=(RequestedChange(node_id=_page_node(state, 2).node_id, text=text),),
        operation_id=operation_id,
    )


def _suggestion_body(
    state: ReviewState,
    *,
    expected_revision: str | None = None,
    operation_id: str | None = None,
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
        operation_id=operation_id,
    )


class AtomicHeads(Heads):
    def __init__(self) -> None:
        super().__init__()
        self._lock = Lock()
        self.gets = 0

    def get(self, job_id: str) -> ReviewHead | None:
        with self._lock:
            self.gets += 1
            return super().get(job_id)

    def publish(self, head: ReviewHead, expected_revision: str | None) -> bool:
        with self._lock:
            return super().publish(head, expected_revision)


class AtomicObjects(Objects):
    def __init__(self, document: object) -> None:
        super().__init__(document)  # type: ignore[arg-type]
        self._lock = Lock()

    def _write(self, key: str, body: bytes, content_type: str) -> Artifact:
        with self._lock:
            return super()._write(key, body, content_type)


def _atomic_service() -> tuple[ReviewService, AtomicHeads, AtomicObjects]:
    document = synthetic_document()
    job = Job(
        id="job",
        owner="alice",
        filename="record.pdf",
        phase="SUCCEEDED",
        created_at=1,
        updated_at=1,
        expires_at=999,
        expected_bytes=10,
        source=SOURCE,
        raw=RAW,
        artifacts={"document.json": BASELINE},
        pages_available=2,
    )
    heads, objects = AtomicHeads(), AtomicObjects(document)
    identifiers = count(1)
    lock = Lock()

    def new_id() -> str:
        with lock:
            return f"00000000-0000-4000-8000-{next(identifiers):012d}"

    service = ReviewService(
        Jobs(job),
        heads,
        objects,
        clock=lambda: 1_700_000_000,
        new_revision_id=new_id,
    )
    return service, heads, objects


def _strip_legacy(payload: dict[str, object]) -> bytes:
    payload["schema_version"] = "1.0.0"
    payload.pop("save_operation", None)
    for change in cast(list[dict[str, object]], payload.get("changes", [])):
        change.pop("origin", None)
        change.pop("finding_id", None)
    return json.dumps(payload, ensure_ascii=False).encode()


def test_legacy_save_omitted_and_null_operation_have_no_receipt() -> None:
    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    omitted = service.update_with_receipt("job", "alice", _manual_body(initial))
    assert isinstance(omitted.state, ReviewState)
    assert omitted.receipt is None
    assert omitted.state.revision is not None
    assert omitted.state.revision.save_operation is None
    assert omitted.state.revision.schema_version == "1.1.0"
    assert all(change.origin == "MANUAL_EDIT" for change in omitted.state.revision.changes)
    null_id = service.update_with_receipt(
        "job",
        "alice",
        _manual_body(
            omitted.state,
            "second correction",
            expected_revision=omitted.state.revision_id,
            operation_id=None,
        ),
    )
    assert null_id.receipt is None
    assert null_id.state.revision is not None
    assert null_id.state.revision.save_operation is None
    with pytest.raises(ReviewError, match="REVIEW_CONFLICT"):
        service.update("job", "alice", _manual_body(initial, operation_id=OP_A))
    assert heads.head is not None
    assert heads.head.revision_id == null_id.state.revision_id
    assert len(objects.writes) == 2


def test_first_operation_aware_save_commits_once_with_receipt() -> None:
    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    result = service.update_with_receipt("job", "alice", _manual_body(initial, operation_id=OP_A))
    assert result.receipt == SaveReceipt(
        operation_id=OP_A,
        revision_id=cast(str, result.state.revision_id),
        generation=1,
        replayed=False,
    )
    revision = result.state.revision
    assert revision is not None
    assert revision.parent is None
    assert revision.generation == 1
    assert revision.actor == "alice"
    assert revision.save_operation is not None
    assert revision.save_operation.operation_id == OP_A
    assert revision.save_operation.fingerprint_version == 1
    assert revision.save_operation.request_fingerprint == save_request_fingerprint(
        "job", "alice", _manual_body(initial, operation_id=OP_A)
    )
    assert heads.head is not None
    assert heads.head.revision_id == revision.revision_id
    assert len(objects.writes) == 1


def test_immediate_replay_returns_original_commit_without_writes() -> None:
    service, _, objects = make_service()
    initial = service.get("job", "alice")
    body = _manual_body(initial, operation_id=OP_A)
    first = service.update_with_receipt("job", "alice", body)
    writes = list(objects.writes)
    replay = service.update_with_receipt("job", "alice", body)
    assert objects.writes == writes
    assert replay.receipt is not None
    assert replay.receipt.replayed is True
    assert replay.receipt.revision_id == first.state.revision_id
    assert replay.state.revision_id == first.state.revision_id
    assert replay.state.pages == first.state.pages


def test_replay_after_newer_revision_identifies_old_commit_and_current_head() -> None:
    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    first_body = _manual_body(initial, operation_id=OP_A)
    first = service.update_with_receipt("job", "alice", first_body)
    second = service.update_with_receipt(
        "job",
        "alice",
        _manual_body(
            first.state,
            "later edit",
            expected_revision=first.state.revision_id,
            operation_id=OP_B,
        ),
    )
    writes = list(objects.writes)
    replay = service.update_with_receipt("job", "alice", first_body)
    assert objects.writes == writes
    assert replay.receipt is not None
    assert replay.receipt.revision_id == first.state.revision_id
    assert replay.receipt.generation == 1
    assert replay.state.revision_id == second.state.revision_id
    assert replay.state.document.pages[1].elements[0].text == "later edit"
    assert heads.head is not None
    assert heads.head.revision_id == second.state.revision_id


def test_replay_after_approval_leaves_approval_current() -> None:
    service, heads, _ = make_service(warnings=False)
    initial = service.get("job", "alice")
    saved = service.update_with_receipt("job", "alice", _manual_body(initial, operation_id=OP_A))
    from app.document_review.contracts import FinalApprovalBody, PageApprovalBody

    page1 = service.approve_page(
        "job", "alice", 1, PageApprovalBody(expected_revision=cast(str, saved.state.revision_id))
    )
    page2 = service.approve_page(
        "job", "alice", 2, PageApprovalBody(expected_revision=cast(str, page1.revision_id))
    )
    approved = service.approve(
        "job", "alice", FinalApprovalBody(expected_revision=cast(str, page2.revision_id))
    )
    assert approved.revision is not None
    assert approved.revision.save_operation is None
    assert approved.revision.schema_version == "1.1.0"
    replay = service.update_with_receipt("job", "alice", _manual_body(initial, operation_id=OP_A))
    assert replay.state.status == "APPROVED"
    assert replay.state.revision_id == approved.revision_id
    assert replay.receipt is not None
    assert replay.receipt.revision_id == saved.state.revision_id
    assert heads.head is not None
    assert heads.head.status == "APPROVED"
    assert approved.revision.document_approval is not None


def test_replay_suggestion_after_changed_context() -> None:
    service, _, objects = make_service()
    initial = service.get("job", "alice")
    suggestion = _suggestion_body(initial, operation_id=OP_A)
    first = service.update_with_receipt("job", "alice", suggestion)
    later = service.update_with_receipt(
        "job",
        "alice",
        _manual_body(
            first.state,
            expected_revision=first.state.revision_id,
            operation_id=OP_B,
        ),
    )
    writes = list(objects.writes)
    replay = service.update_with_receipt("job", "alice", suggestion)
    assert objects.writes == writes
    assert replay.receipt is not None
    assert replay.receipt.revision_id == first.state.revision_id
    assert replay.state.revision_id == later.state.revision_id


def test_same_id_changed_request_is_mismatch_without_writes() -> None:
    service, _, objects = make_service()
    initial = service.get("job", "alice")
    first = service.update_with_receipt("job", "alice", _manual_body(initial, operation_id=OP_A))
    service.update_with_receipt(
        "job",
        "alice",
        _manual_body(
            first.state,
            "later edit",
            expected_revision=first.state.revision_id,
            operation_id=OP_B,
        ),
    )
    writes = list(objects.writes)
    with pytest.raises(ReviewError, match="SAVE_OPERATION_MISMATCH"):
        service.update_with_receipt(
            "job", "alice", _manual_body(initial, "different text", operation_id=OP_A)
        )
    assert objects.writes == writes


def test_fingerprint_determinism_and_duplicate_rejection() -> None:
    replacement = RequestedChange(node_id="n1", text="Tolerance ±0.1")
    ordered = UpdateReviewBody(
        expected_revision=None,
        changes=(
            RequestedChange(node_id="b", text="two"),
            RequestedChange(node_id="a", text="one"),
        ),
        decisions=(
            FindingDecisionRequest(finding_id="f2", action="KEEP_ORIGINAL", note="n"),
            FindingDecisionRequest(
                finding_id="f1",
                action="RESOLVED_AFTER_EDIT",
                replacement=replacement,
                expected_region_hash="hash",
            ),
        ),
        operation_id=OP_A,
    )
    resorted = UpdateReviewBody(
        expected_revision=None,
        changes=(
            RequestedChange(node_id="a", text="one"),
            RequestedChange(node_id="b", text="two"),
        ),
        decisions=(
            FindingDecisionRequest(
                finding_id="f1",
                action="RESOLVED_AFTER_EDIT",
                note=None,
                replacement=replacement,
                expected_region_hash="hash",
            ),
            FindingDecisionRequest(
                finding_id="f2", action="KEEP_ORIGINAL", note="n", replacement=None
            ),
        ),
        operation_id=OP_A,
    )
    omitted = UpdateReviewBody(
        expected_revision=None,
        changes=ordered.changes[::-1],
        decisions=(
            FindingDecisionRequest(
                finding_id="f1",
                action="RESOLVED_AFTER_EDIT",
                replacement=replacement,
                expected_region_hash="hash",
            ),
            FindingDecisionRequest(finding_id="f2", action="KEEP_ORIGINAL", note="n"),
        ),
    )
    assert save_request_fingerprint("job", "alice", ordered) == save_request_fingerprint(
        "job", "alice", resorted
    )
    assert save_request_fingerprint("job", "alice", ordered) == save_request_fingerprint(
        "job", "alice", omitted
    )
    changed_text = UpdateReviewBody(
        expected_revision=None,
        changes=(
            RequestedChange(node_id="a", text="one "),
            RequestedChange(node_id="b", text="two"),
        ),
        decisions=resorted.decisions,
    )
    assert save_request_fingerprint("job", "alice", changed_text) != save_request_fingerprint(
        "job", "alice", resorted
    )
    plus = UpdateReviewBody(changes=(RequestedChange(node_id="a", text="Toler +0.1%"),))
    pm = UpdateReviewBody(changes=(RequestedChange(node_id="a", text="Toler ±0.1%"),))
    assert save_request_fingerprint("job", "alice", plus) != save_request_fingerprint(
        "job", "alice", pm
    )
    service, _, objects = make_service()
    duplicate = UpdateReviewBody(
        changes=(
            RequestedChange(node_id="same", text="a"),
            RequestedChange(node_id="same", text="b"),
        ),
        operation_id=OP_A,
    )
    with pytest.raises(ReviewError, match="INVALID_REVIEW"):
        service.update("job", "alice", duplicate)
    assert objects.writes == []


def _fingerprint_base() -> UpdateReviewBody:
    return UpdateReviewBody(
        expected_revision=None,
        changes=(RequestedChange(node_id="n1", text="one"),),
        decisions=(
            FindingDecisionRequest(
                finding_id="f1",
                action="KEEP_ORIGINAL",
                note="checked",
                replacement=RequestedChange(node_id="n1", text="one"),
                expected_region_hash="region-a",
            ),
        ),
        operation_id=OP_A,
    )


@pytest.mark.parametrize(
    ("job_id", "actor", "body"),
    [
        ("job-b", "alice", _fingerprint_base()),
        ("job", "bob", _fingerprint_base()),
        (
            "job",
            "alice",
            _fingerprint_base().model_copy(
                update={"expected_revision": "00000000-0000-4000-8000-000000000001"}
            ),
        ),
        (
            "job",
            "alice",
            _fingerprint_base().model_copy(
                update={
                    "decisions": (
                        _fingerprint_base()
                        .decisions[0]
                        .model_copy(update={"action": "ACKNOWLEDGED_LIMITATION"}),
                    )
                }
            ),
        ),
        (
            "job",
            "alice",
            _fingerprint_base().model_copy(
                update={
                    "decisions": (
                        _fingerprint_base().decisions[0].model_copy(update={"note": "other"}),
                    )
                }
            ),
        ),
        (
            "job",
            "alice",
            _fingerprint_base().model_copy(
                update={
                    "decisions": (
                        _fingerprint_base()
                        .decisions[0]
                        .model_copy(
                            update={"replacement": RequestedChange(node_id="n2", text="one")}
                        ),
                    )
                }
            ),
        ),
        (
            "job",
            "alice",
            _fingerprint_base().model_copy(
                update={
                    "decisions": (
                        _fingerprint_base()
                        .decisions[0]
                        .model_copy(
                            update={"replacement": RequestedChange(node_id="n1", text="two")}
                        ),
                    )
                }
            ),
        ),
        (
            "job",
            "alice",
            _fingerprint_base().model_copy(
                update={
                    "decisions": (
                        _fingerprint_base()
                        .decisions[0]
                        .model_copy(update={"expected_region_hash": "region-b"}),
                    )
                }
            ),
        ),
    ],
)
def test_fingerprint_changes_for_significant_fields(
    job_id: str, actor: str, body: UpdateReviewBody
) -> None:
    baseline = save_request_fingerprint("job", "alice", _fingerprint_base())
    assert save_request_fingerprint(job_id, actor, body) != baseline


def test_committed_operation_mismatch_after_newer_head() -> None:
    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    committed = _suggestion_body(initial, operation_id=OP_A)
    first = service.update_with_receipt("job", "alice", committed)
    later = service.update_with_receipt(
        "job",
        "alice",
        _manual_body(
            first.state,
            "later edit",
            expected_revision=first.state.revision_id,
            operation_id=OP_B,
        ),
    )
    suggestion = committed.decisions[0]
    assert suggestion.replacement is not None
    variants = (
        committed.model_copy(update={"expected_revision": later.state.revision_id}),
        committed.model_copy(
            update={"decisions": (suggestion.model_copy(update={"action": "KEEP_ORIGINAL"}),)}
        ),
        committed.model_copy(
            update={"decisions": (suggestion.model_copy(update={"note": "changed note"}),)}
        ),
        committed.model_copy(
            update={
                "decisions": (
                    suggestion.model_copy(
                        update={
                            "replacement": RequestedChange(
                                node_id=_page_node(initial, 2).node_id,
                                text=suggestion.replacement.text,
                            )
                        }
                    ),
                )
            }
        ),
        committed.model_copy(
            update={
                "decisions": (
                    suggestion.model_copy(
                        update={
                            "replacement": RequestedChange(
                                node_id=suggestion.replacement.node_id, text="other text"
                            )
                        }
                    ),
                )
            }
        ),
        committed.model_copy(
            update={
                "decisions": (suggestion.model_copy(update={"expected_region_hash": "stale-hash"}),)
            }
        ),
    )
    writes = list(objects.writes)
    head_id = later.state.revision_id
    for variant in variants:
        with pytest.raises(ReviewError, match="SAVE_OPERATION_MISMATCH"):
            service.update_with_receipt("job", "alice", variant)
        assert objects.writes == writes
        assert heads.head is not None
        assert heads.head.revision_id == head_id


class SharedJobs:
    def __init__(self, *jobs: Job) -> None:
        self._jobs = {job.id: job for job in jobs}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)


class SharedHeads:
    def __init__(self) -> None:
        self._heads: dict[str, ReviewHead] = {}
        self.gets = 0

    def get(self, job_id: str) -> ReviewHead | None:
        self.gets += 1
        return self._heads.get(job_id)

    def publish(self, head: ReviewHead, expected_revision: str | None) -> bool:
        current = self._heads.get(head.job_id)
        current_revision = current.revision_id if current is not None else None
        if current_revision != expected_revision:
            return False
        self._heads[head.job_id] = head
        return True


class SharedObjects(Objects):
    def __init__(self, document: object) -> None:
        super().__init__(document)  # type: ignore[arg-type]
        self.read_keys: list[str] = []

    def read(self, artifact: Artifact) -> bytes:
        self.read_keys.append(artifact.key)
        return super().read(artifact)


def _shared_job(job_id: str, owner: str) -> Job:
    return Job(
        id=job_id,
        owner=owner,
        filename="record.pdf",
        phase="SUCCEEDED",
        created_at=1,
        updated_at=1,
        expires_at=999,
        expected_bytes=10,
        source=SOURCE,
        raw=RAW,
        artifacts={"document.json": BASELINE},
        pages_available=2,
    )


def test_shared_store_isolates_same_operation_id_across_jobs() -> None:
    identifiers = count(1)

    def new_id() -> str:
        return f"00000000-0000-4000-8000-{next(identifiers):012d}"

    jobs = SharedJobs(_shared_job("job-a", "alice"), _shared_job("job-b", "bob"))
    heads = SharedHeads()
    objects = SharedObjects(synthetic_document())
    service = ReviewService(
        jobs,
        heads,
        objects,
        clock=lambda: 1_700_000_000,
        new_revision_id=new_id,
    )
    alice_initial = service.get("job-a", "alice")
    bob_initial = service.get("job-b", "bob")
    alice_body = _manual_body(alice_initial, "alice text", operation_id=OP_A)
    bob_body = _manual_body(bob_initial, "bob text", operation_id=OP_A)
    alice = service.update_with_receipt("job-a", "alice", alice_body)
    bob = service.update_with_receipt("job-b", "bob", bob_body)
    assert alice.receipt is not None and bob.receipt is not None
    assert alice.receipt.revision_id != bob.receipt.revision_id
    assert alice.state.revision is not None and bob.state.revision is not None
    assert alice.state.revision.job_id == "job-a"
    assert bob.state.revision.job_id == "job-b"
    assert alice.state.document.pages[1].elements[0].text == "alice text"
    assert bob.state.document.pages[1].elements[0].text == "bob text"
    writes = list(objects.writes)
    alice_replay = service.update_with_receipt("job-a", "alice", alice_body)
    bob_replay = service.update_with_receipt("job-b", "bob", bob_body)
    assert objects.writes == writes
    assert alice_replay.receipt is not None
    assert bob_replay.receipt is not None
    assert alice_replay.receipt.revision_id == alice.receipt.revision_id
    assert bob_replay.receipt.revision_id == bob.receipt.revision_id
    assert alice_replay.state.document.pages[1].elements[0].text == "alice text"
    assert bob_replay.state.document.pages[1].elements[0].text == "bob text"
    gets_before = heads.gets
    review_reads_before = list(objects.read_keys)
    with pytest.raises(ReviewError, match="JOB_NOT_FOUND"):
        service.update_with_receipt("job-a", "bob", alice_body)
    with pytest.raises(ReviewError, match="JOB_NOT_FOUND"):
        service.reconcile_save_operation("job-b", "alice", OP_A)
    assert heads.gets == gets_before
    assert objects.read_keys == review_reads_before


def test_scope_isolation_rejects_other_actor_before_history_read() -> None:
    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    service.update_with_receipt("job", "alice", _manual_body(initial, operation_id=OP_A))
    reads_before = objects.source_reads
    get_calls = {"count": 0}
    original_get = heads.get

    def counting_get(job_id: str) -> ReviewHead | None:
        get_calls["count"] += 1
        return original_get(job_id)

    heads.get = counting_get  # type: ignore[method-assign]
    with pytest.raises(ReviewError, match="JOB_NOT_FOUND"):
        service.update_with_receipt("job", "bob", _manual_body(initial, operation_id=OP_A))
    with pytest.raises(ReviewError, match="JOB_NOT_FOUND"):
        service.reconcile_save_operation("job", "bob", OP_A)
    assert get_calls["count"] == 0
    assert objects.source_reads == reads_before

    other, other_heads, _ = make_service()
    other.jobs = Jobs(
        Job(
            id="job-b",
            owner="alice",
            filename="record.pdf",
            phase="SUCCEEDED",
            created_at=1,
            updated_at=1,
            expires_at=999,
            expected_bytes=10,
            source=SOURCE,
            raw=RAW,
            artifacts={"document.json": BASELINE},
            pages_available=2,
        )
    )
    other_initial = other.get("job-b", "alice")
    other.update_with_receipt("job-b", "alice", _manual_body(other_initial, operation_id=OP_A))
    replay = service.update_with_receipt("job", "alice", _manual_body(initial, operation_id=OP_A))
    assert other_heads.head is not None
    assert other_heads.head.job_id == "job-b"
    assert replay.state.revision is not None
    assert replay.state.revision.job_id == "job"
    assert replay.receipt is not None
    assert replay.receipt.replayed is True
    assert replay.state.generation == 1


def test_in_flight_absence_is_unresolved_until_commit() -> None:
    service, heads, _ = _atomic_service()
    reached = Event()
    release = Event()
    original_publish = heads.publish

    def gated_publish(head: ReviewHead, expected_revision: str | None) -> bool:
        reached.set()
        assert release.wait(timeout=5)
        return original_publish(head, expected_revision)

    heads.publish = gated_publish  # type: ignore[method-assign]
    initial = service.get("job", "alice")
    body = _manual_body(initial, operation_id=OP_A)
    outcome: list[UpdateResult | BaseException] = []

    def run() -> None:
        try:
            outcome.append(service.update_with_receipt("job", "alice", body))
        except BaseException as error:  # noqa: BLE001
            outcome.append(error)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        assert reached.wait(timeout=5)
        pending = service.reconcile_save_operation("job", "alice", OP_A)
        assert pending.status == "UNRESOLVED"
        assert pending.head_generation == 0
        assert pending.receipt is None
        release.set()
        future.result(timeout=5)
    assert outcome and isinstance(outcome[0], UpdateResult)
    committed = service.reconcile_save_operation("job", "alice", OP_A)
    assert committed.status == "COMMITTED"
    assert committed.receipt is not None
    assert committed.receipt.revision_id == outcome[0].state.revision_id


def test_concurrent_identical_requests_commit_once_and_share_receipt() -> None:
    service, heads, objects = _atomic_service()
    barrier = Barrier(2)
    original_publish = heads.publish

    def barrier_publish(head: ReviewHead, expected_revision: str | None) -> bool:
        barrier.wait(timeout=5)
        return original_publish(head, expected_revision)

    heads.publish = barrier_publish  # type: ignore[method-assign]
    initial = service.get("job", "alice")
    body = _manual_body(initial, operation_id=OP_A)

    def run(_: int) -> UpdateResult | ReviewError:
        try:
            return service.update_with_receipt("job", "alice", body)
        except ReviewError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    successes = [item for item in results if isinstance(item, UpdateResult)]
    assert len(successes) == 2
    committed = {item.receipt.revision_id for item in successes if item.receipt is not None}
    assert len(committed) == 1
    assert heads.head is not None
    assert heads.head.revision_id in committed
    assert all(item.receipt is not None and item.receipt.operation_id == OP_A for item in successes)
    assert sum(1 for item in successes if item.receipt and item.receipt.replayed) == 1
    assert any(write.key.endswith("review.json") for write in objects.writes)


def test_concurrent_different_requests_conflict_or_mismatch() -> None:
    service, heads, _ = _atomic_service()
    barrier = Barrier(2)
    original_publish = heads.publish

    def barrier_publish(head: ReviewHead, expected_revision: str | None) -> bool:
        barrier.wait(timeout=5)
        return original_publish(head, expected_revision)

    heads.publish = barrier_publish  # type: ignore[method-assign]
    initial = service.get("job", "alice")
    first = _manual_body(initial, "first", operation_id=OP_A)
    second = _manual_body(initial, "second", operation_id=OP_B)

    def run(body: UpdateReviewBody) -> UpdateResult | ReviewError:
        try:
            return service.update_with_receipt("job", "alice", body)
        except ReviewError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(run, first)
        right = pool.submit(run, second)
        results = [left.result(timeout=5), right.result(timeout=5)]
    successes = [item for item in results if isinstance(item, UpdateResult)]
    errors = [item for item in results if isinstance(item, ReviewError)]
    assert len(successes) == 1 and len(errors) == 1
    assert errors[0].code == "REVIEW_CONFLICT"
    assert heads.head is not None
    assert successes[0].state.revision_id == heads.head.revision_id

    mismatch_service, mismatch_heads, _ = _atomic_service()
    barrier_b = Barrier(2)
    original = mismatch_heads.publish

    def barrier_publish_b(head: ReviewHead, expected_revision: str | None) -> bool:
        barrier_b.wait(timeout=5)
        return original(head, expected_revision)

    mismatch_heads.publish = barrier_publish_b  # type: ignore[method-assign]
    start = mismatch_service.get("job", "alice")
    same_id_a = _manual_body(start, "first", operation_id=OP_A)
    same_id_b = _manual_body(start, "second", operation_id=OP_A)

    def run_mismatch(body: UpdateReviewBody) -> UpdateResult | ReviewError:
        try:
            return mismatch_service.update_with_receipt("job", "alice", body)
        except ReviewError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(run_mismatch, same_id_a)
        second_future = pool.submit(run_mismatch, same_id_b)
        results = [first_future.result(timeout=5), second_future.result(timeout=5)]
    codes = {item.code for item in results if isinstance(item, ReviewError)}
    wins = [item for item in results if isinstance(item, UpdateResult)]
    assert len(wins) == 1
    assert codes == {"SAVE_OPERATION_MISMATCH"}


def test_failure_before_publication_has_no_receipt_and_retry_can_succeed() -> None:
    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    body = _manual_body(initial, operation_id=OP_A)

    def fail_write(*_args: object, **_kwargs: object) -> Artifact:
        raise OSError("object write failed")

    objects.put_revision = fail_write  # type: ignore[method-assign]
    with pytest.raises(OSError, match="object write failed"):
        service.update_with_receipt("job", "alice", body)
    assert heads.head is None

    def restore(job_id: str, revision_id: str, body: bytes) -> Artifact:
        return Objects.put_revision(objects, job_id, revision_id, body)

    objects.put_revision = restore  # type: ignore[method-assign]
    result = service.update_with_receipt("job", "alice", body)
    assert result.receipt is not None
    assert result.receipt.replayed is False
    assert heads.head is not None


def test_ambiguous_publication_retry_discovers_commit() -> None:
    service, heads, objects = make_service()
    original_publish = heads.publish

    def commit_then_raise(head: ReviewHead, expected_revision: str | None) -> bool:
        committed = original_publish(head, expected_revision)
        if committed:
            raise OSError("connection reset after commit")
        return committed

    heads.publish = commit_then_raise  # type: ignore[method-assign]
    initial = service.get("job", "alice")
    body = _manual_body(initial, operation_id=OP_A)
    with pytest.raises(OSError, match="connection reset"):
        service.update_with_receipt("job", "alice", body)
    assert heads.head is not None
    writes = list(objects.writes)
    heads.publish = original_publish  # type: ignore[method-assign]
    retry = service.update_with_receipt("job", "alice", body)
    assert objects.writes == writes
    assert retry.receipt is not None
    assert retry.receipt.replayed is True
    assert retry.receipt.revision_id == heads.head.revision_id


def test_lost_response_retry_uses_retained_store_not_service_memory() -> None:
    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    body = _manual_body(initial, operation_id=OP_A)
    first = service.update_with_receipt("job", "alice", body)
    committed_id = first.state.revision_id
    restored = ReviewService(
        service.jobs,
        heads,
        objects,
        clock=lambda: 1_700_000_000,
        new_revision_id=lambda: IDS[10],
    )
    writes = list(objects.writes)
    retry = restored.update_with_receipt("job", "alice", body)
    assert objects.writes == writes
    assert retry.receipt is not None
    assert retry.receipt.replayed is True
    assert retry.state.revision_id == committed_id


def test_history_failures_are_invalid_not_unresolved() -> None:
    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    first = service.update_with_receipt("job", "alice", _manual_body(initial, operation_id=OP_A))
    second = service.update_with_receipt(
        "job",
        "alice",
        _manual_body(
            first.state,
            "later",
            expected_revision=first.state.revision_id,
            operation_id=OP_B,
        ),
    )
    parent = second.state.revision.parent if second.state.revision else None
    assert parent is not None
    objects.data.pop((parent.key, parent.version))
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        service.reconcile_save_operation("job", "alice", OP_A)
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        service.update_with_receipt(
            "job",
            "alice",
            _manual_body(
                second.state, "third", expected_revision=second.state.revision_id, operation_id=OP_C
            ),
        )
    assert heads.head is not None
    assert heads.head.revision_id == second.state.revision_id

    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    service.update_with_receipt("job", "alice", _manual_body(initial, operation_id=OP_A))
    artifact = heads.head.revision if heads.head else None
    assert artifact is not None
    payload = json.loads(objects.read(artifact))
    payload["save_operation"]["fingerprint_version"] = 2
    objects.data[(artifact.key, artifact.version)] = json.dumps(payload).encode()
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        service.update_with_receipt("job", "alice", _manual_body(initial, operation_id=OP_A))

    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    first = service.update_with_receipt("job", "alice", _manual_body(initial, operation_id=OP_A))
    second = service.update_with_receipt(
        "job",
        "alice",
        _manual_body(
            first.state, "later", expected_revision=first.state.revision_id, operation_id=OP_B
        ),
    )
    child = heads.head.revision if heads.head else None
    assert child is not None
    payload = json.loads(objects.read(child))
    payload["save_operation"]["operation_id"] = OP_A
    objects.data[(child.key, child.version)] = json.dumps(payload).encode()
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        service.reconcile_save_operation("job", "alice", OP_A)

    service, _, objects = make_service()
    initial = service.get("job", "alice")
    first = service.update_with_receipt("job", "alice", _manual_body(initial, operation_id=OP_A))
    second = service.update_with_receipt(
        "job",
        "alice",
        _manual_body(
            first.state, "later", expected_revision=first.state.revision_id, operation_id=OP_B
        ),
    )
    parent = second.state.revision.parent if second.state.revision else None
    assert parent is not None
    payload = json.loads(objects.read(parent))
    payload["job_id"] = "other-job"
    objects.data[(parent.key, parent.version)] = json.dumps(payload).encode()
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        service.reconcile_save_operation("job", "alice", OP_B)

    service, _, objects = make_service()
    initial = service.get("job", "alice")
    first = service.update_with_receipt("job", "alice", _manual_body(initial, operation_id=OP_A))
    second = service.update_with_receipt(
        "job",
        "alice",
        _manual_body(
            first.state, "later", expected_revision=first.state.revision_id, operation_id=OP_B
        ),
    )
    parent = second.state.revision.parent if second.state.revision else None
    assert parent is not None
    payload = json.loads(objects.read(parent))
    payload["generation"] = 2
    objects.data[(parent.key, parent.version)] = json.dumps(payload).encode()
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        service.update_with_receipt(
            "job",
            "alice",
            _manual_body(
                second.state, "third", expected_revision=second.state.revision_id, operation_id=OP_C
            ),
        )


def test_legacy_mixed_chain_keeps_old_bytes_and_unknown_provenance() -> None:
    service, heads, objects = make_service()
    initial = service.get("job", "alice")
    service.update_with_receipt("job", "alice", _manual_body(initial))
    artifact = heads.head.revision if heads.head else None
    assert artifact is not None
    stripped = _strip_legacy(json.loads(objects.read(artifact)))
    assert b"save_operation" not in stripped
    assert b'"origin"' not in stripped
    objects.data[(artifact.key, artifact.version)] = stripped
    loaded = service.get("job", "alice")
    assert loaded.revision is not None
    assert loaded.revision.schema_version == "1.0.0"
    assert loaded.revision.save_operation is None
    assert loaded.revision.changes[0].origin is None
    assert loaded.revision.changes[0].finding_id is None
    newer = service.update_with_receipt(
        "job",
        "alice",
        _manual_body(
            loaded, "mixed chain", expected_revision=loaded.revision_id, operation_id=OP_A
        ),
    )
    assert newer.state.revision is not None
    assert newer.state.revision.schema_version == "1.1.0"
    assert newer.state.revision.save_operation is not None
    assert objects.read(artifact) == stripped
    parsed = ReviewRevision.model_validate_json(stripped)
    assert parsed.save_operation is None


def test_change_provenance_manual_versus_applied_suggestion() -> None:
    service, _, _ = make_service()
    initial = service.get("job", "alice")
    finding = initial.findings[0]
    suggestion = finding.suggested_replacement
    assert suggestion is not None
    applied = service.update_with_receipt(
        "job", "alice", _suggestion_body(initial, operation_id=OP_A)
    )
    assert applied.state.revision is not None
    change = applied.state.revision.changes[0]
    assert change.origin == "APPLIED_SUGGESTION"
    assert change.finding_id == finding.finding_id
    assert change.new_text == suggestion.text

    service, _, _ = make_service()
    initial = service.get("job", "alice")
    finding = initial.findings[0]
    suggestion = finding.suggested_replacement
    assert suggestion is not None
    manual = service.update_with_receipt(
        "job",
        "alice",
        UpdateReviewBody(
            changes=(RequestedChange(node_id=suggestion.node_id, text=suggestion.text),),
            decisions=(
                FindingDecisionRequest(
                    finding_id=finding.finding_id,
                    action="RESOLVED_AFTER_EDIT",
                    expected_region_hash=finding.region_hash,
                ),
            ),
            operation_id=OP_B,
        ),
    )
    assert manual.state.revision is not None
    change = manual.state.revision.changes[0]
    assert change.origin == "MANUAL_EDIT"
    assert change.finding_id is None
    assert change.new_text == suggestion.text

    service, _, objects = make_service()
    initial = service.get("job", "alice")
    acknowledged = service.update_with_receipt(
        "job",
        "alice",
        UpdateReviewBody(
            decisions=(
                FindingDecisionRequest(
                    finding_id=initial.findings[0].finding_id,
                    action="ACKNOWLEDGED_LIMITATION",
                ),
            ),
            operation_id=OP_C,
        ),
    )
    assert acknowledged.state.revision is not None
    assert acknowledged.state.revision.changes == ()
    assert acknowledged.state.findings[0].decision is not None
    assert objects.writes


def test_invalid_operation_id_is_rejected_by_contract() -> None:
    with pytest.raises(ValidationError):
        UpdateReviewBody(operation_id="not-a-uuid")

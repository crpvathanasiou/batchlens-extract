"""Concurrent, resumable, owner-isolated job semantics at the API and worker boundaries."""

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.documents import install_errors, router
from app.document_conversion.aws import AwsError
from app.document_conversion.contracts import Document
from app.document_jobs.contracts import Artifact, Job, JobError, JobStatus
from app.document_jobs.service import JobService
from app.document_jobs.worker import process_job
from tests.document_conversion.job_fakes import (
    Provider,
    QueueFake,
    Store,
    WorkerCrash,
    make_service,
)


def accept(service: JobService, owner: str = "alice") -> str:
    job_id = service.initiate(owner, "record.pdf", 9).job_id
    assert service.start(job_id, owner).phase == "QUEUED"
    return job_id


def ready(service: JobService, job_id: str) -> None:
    job = service.store.get(job_id)
    assert job is not None
    service.save(job.model_copy(update={"next_due": 0}))


def uncertain_after_accept_crash(
    service: JobService, store: Store, provider: Provider, *, active_jobs: int = 1
) -> str:
    """Provider accepts StartDocumentAnalysis, then worker dies before handle persistence."""
    service.settings = service.settings.model_copy(update={"active_jobs": active_jobs})
    job_id = accept(service)
    provider.crash_after_accept = True
    with pytest.raises(WorkerCrash):
        process_job(service, job_id)
    crashed = service.owned(job_id, "alice")
    assert crashed.phase == "SUBMITTING"
    assert crashed.unknown_submission and crashed.handle is None
    assert crashed.slot is not None and crashed.slot_generation is not None
    assert store.slots == {crashed.slot: (job_id, crashed.slot_generation)}
    assert job_id in provider.started
    return job_id


def test_restart_duplicate_messages_and_two_concurrent_isolated_jobs() -> None:
    service, store, objects, provider = make_service()
    first, second = accept(service), accept(service, "bob")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(partial(process_job, service), [first, second]))
    assert len(provider.started) == 2 and len(store.slots) == 2
    # Fresh service instance sees serialized metadata and the exact persisted handles.
    restarted = JobService(
        store, objects, service.queue, service.textract, service.settings, clock=service.clock
    )
    for job_id in [first, second]:
        ready(restarted, job_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(partial(process_job, restarted), [first, second]))
    before = dict(objects.data)
    process_job(restarted, first)
    assert objects.data == before and provider.calls == 2 and not store.slots
    a, b = restarted.owned(first, "alice"), restarted.owned(second, "bob")
    assert a.phase == b.phase == "SUCCEEDED" and a.pages_available == 2
    assert {x.key for x in a.artifacts.values()}.isdisjoint(x.key for x in b.artifacts.values())
    html = objects.read(a.artifacts["document.html"]).decode()
    # Textractor renderer uses id="source-page-N" for page sections.
    assert html.index('id="source-page-1"') < html.index('id="source-page-2"')
    with pytest.raises(JobError, match="JOB_NOT_FOUND"):
        restarted.download(first, "bob", "document.html")


def test_enqueue_failure_is_recovered_from_persisted_due_state() -> None:
    service, _, _, provider = make_service()
    queue = cast(QueueFake, service.queue)
    queue.fail = True
    job_id = accept(service)
    assert not provider.started and not queue.messages
    queue.fail = False
    assert service.dispatch_due() == 1 and queue.messages == [job_id]
    process_job(service, job_id)
    assert len(provider.started) == 1


def test_submission_response_loss_and_retry_use_same_token_and_source() -> None:
    service, _, _, provider = make_service()
    job_id = accept(service)
    provider.fail_after_submit = True
    process_job(service, job_id)
    assert service.owned(job_id, "alice").phase == "SUBMITTING"
    ready(service, job_id)
    process_job(service, job_id)
    assert len(provider.started) == 1 and provider.calls == 2
    assert service.owned(job_id, "alice").handle is not None


def test_upload_replay_cannot_change_accepted_source_and_duplicate_start_is_prompt() -> None:
    service, _, objects, provider = make_service()
    job_id = accept(service)
    objects.version = "replayed-version-two"
    assert service.start(job_id, "alice").phase == "QUEUED"
    assert service.owned(job_id, "alice").source.version == "version-one"
    assert provider.calls == 0
    process_job(service, job_id)
    assert provider.sources[job_id]["S3Object"]["Version"] == "version-one"


def test_global_slot_backpressure_and_recovery_of_slot_before_job_commit() -> None:
    service, store, _, provider = make_service()
    jobs = [accept(service) for _ in range(3)]
    assert store.acquire_slot(jobs[0], 2) is not None  # Simulate crash before saving Job.slot.
    assert store.slots[0][0] == jobs[0]
    for job_id in jobs:
        process_job(service, job_id)
    assert len(provider.started) == 2 and len(store.slots) == 2
    assert service.owned(jobs[2], "alice").phase == "QUEUED"


@pytest.mark.parametrize("state", ["PARTIAL_SUCCESS", "FAILED"])
def test_partial_and_failed_completion_are_distinct(state: str) -> None:
    service, store, _, provider = make_service()
    provider.state = state
    job_id = accept(service)
    process_job(service, job_id)
    ready(service, job_id)
    process_job(service, job_id)
    result = service.owned(job_id, "alice")
    assert result.phase == state
    assert bool(result.artifacts) == (state == "PARTIAL_SUCCESS")
    assert not store.slots


def test_expired_worker_lease_is_recovered_and_old_owner_cannot_write() -> None:
    service, store, _, _ = make_service()
    job_id = accept(service)
    job = service.owned(job_id, "alice")
    old_lease = store.claim(job, 1, 180)
    assert old_lease
    process_job(service, job_id)
    assert service.owned(job_id, "alice").phase == "OCR"
    assert not store.replace(job, job.revision, old_lease)


def test_terminal_commit_before_slot_release_is_reconciled() -> None:
    service, store, _, _ = make_service()
    job_id = accept(service)
    process_job(service, job_id)
    job = service.owned(job_id, "alice")
    service.save(job.model_copy(update={"phase": "FAILED", "ocr_finished": True}))
    assert store.slots
    service.dispatch_due()
    assert not store.slots


def test_retry_exhaustion_retains_uncertain_ocr_slot_then_resumes_handle() -> None:
    service, store, _, provider = make_service()
    service.settings = service.settings.model_copy(update={"max_failures": 1})
    job_id = accept(service)
    provider.fail_after_submit = True
    process_job(service, job_id)
    failed = service.owned(job_id, "alice")
    assert failed.phase == "FAILED" and failed.retry_phase == "SUBMITTING" and store.slots
    assert failed.unknown_submission
    service.retry(job_id, "alice")
    process_job(service, job_id)
    assert service.owned(job_id, "alice").phase == "OCR" and len(provider.started) == 1


def test_definitive_submit_rejections_release_capacity_for_third_job() -> None:
    service, store, _, provider = make_service()
    first, second, third = accept(service), accept(service), accept(service)
    provider.reject_with = "AccessDeniedException"
    process_job(service, first)
    process_job(service, second)
    for job_id in (first, second):
        failed = service.owned(job_id, "alice")
        assert failed.phase == "FAILED"
        assert failed.retry_phase == "QUEUED"
        assert not failed.unknown_submission
        assert failed.error_code == "AccessDeniedException"
    assert not store.slots and not provider.started
    provider.reject_with = None
    process_job(service, third)
    assert service.owned(third, "alice").phase == "OCR" and len(provider.started) == 1


def test_retry_after_definitive_rejection_reacquires_capacity() -> None:
    service, store, _, provider = make_service()
    rejected = accept(service)
    provider.reject_with = "AccessDeniedException"
    process_job(service, rejected)
    assert service.owned(rejected, "alice").retry_phase == "QUEUED" and not store.slots
    provider.reject_with = None
    blockers = [accept(service) for _ in range(2)]
    for job_id in blockers:
        process_job(service, job_id)
    assert len(store.slots) == 2 and len(provider.started) == 2
    service.retry(rejected, "alice")
    process_job(service, rejected)
    waiting = service.owned(rejected, "alice")
    holders = {owner for owner, _generation in store.slots.values()}
    assert waiting.phase == "QUEUED" and rejected not in holders
    assert rejected not in provider.started
    # Free one slot; the resumed job must acquire it before submitting.
    done = service.owned(blockers[0], "alice")
    service.save(done.model_copy(update={"phase": "SUCCEEDED", "ocr_finished": True}))
    service.dispatch_due()
    ready(service, rejected)
    process_job(service, rejected)
    assert service.owned(rejected, "alice").phase == "OCR"
    assert rejected in provider.started


def test_uncertain_submission_keeps_slot_despite_later_rejection() -> None:
    service, store, _, provider = make_service()
    service.settings = service.settings.model_copy(update={"max_failures": 1, "active_jobs": 1})
    job_id = accept(service)
    provider.fail_after_submit = True
    process_job(service, job_id)
    failed = service.owned(job_id, "alice")
    assert failed.unknown_submission and store.slots and failed.retry_phase == "SUBMITTING"
    service.retry(job_id, "alice")
    provider.reject_with = "AccessDeniedException"
    process_job(service, job_id)
    retained = service.owned(job_id, "alice")
    assert retained.phase == "FAILED" and retained.unknown_submission
    assert retained.retry_phase == "SUBMITTING" and store.slots
    # Capacity must stay reserved; a sibling job cannot steal the uncertain slot.
    provider.reject_with = None
    sibling = accept(service)
    process_job(service, sibling)
    assert service.owned(sibling, "alice").phase == "QUEUED"
    assert len(provider.started) == 1 and job_id in provider.started


def test_interrupted_definitive_rejection_slot_cleanup_is_recoverable() -> None:
    service, store, _, provider = make_service()
    job_id = accept(service)
    provider.reject_with = "AccessDeniedException"
    process_job(service, job_id)
    failed = service.owned(job_id, "alice")
    assert failed.phase == "FAILED" and not failed.unknown_submission
    # Crash after FAILED commit but before slot delete: restore the durable slot row.
    assert failed.slot is not None and failed.slot_generation is not None
    store.slots[failed.slot] = (job_id, failed.slot_generation)
    assert store.slots
    service.dispatch_due()
    assert not store.slots
    provider.reject_with = None
    other = accept(service)
    process_job(service, other)
    assert service.owned(other, "alice").phase == "OCR" and len(provider.started) == 1


def test_crash_before_handle_persists_uncertainty_for_later_rejection() -> None:
    service, store, _, provider = make_service()
    service.settings = service.settings.model_copy(update={"active_jobs": 1})
    job_id = accept(service)
    provider.crash_after_accept = True
    with pytest.raises(WorkerCrash):
        process_job(service, job_id)
    crashed = service.owned(job_id, "alice")
    assert crashed.phase == "SUBMITTING"
    assert crashed.unknown_submission and crashed.handle is None and store.slots
    assert job_id in provider.started
    provider.reject_with = "AccessDeniedException"
    process_job(service, job_id)
    retained = service.owned(job_id, "alice")
    assert retained.phase == "FAILED" and retained.unknown_submission
    assert retained.retry_phase == "SUBMITTING" and store.slots
    provider.reject_with = None
    sibling = accept(service)
    process_job(service, sibling)
    assert service.owned(sibling, "alice").phase == "QUEUED"
    assert len(provider.started) == 1


def test_stale_terminal_cleanup_cannot_drop_reactivated_slot() -> None:
    service, store, _, provider = make_service()
    service.settings = service.settings.model_copy(update={"active_jobs": 1})
    job_id = accept(service)
    provider.reject_with = "AccessDeniedException"
    process_job(service, job_id)
    failed = service.owned(job_id, "alice")
    assert failed.retry_phase == "QUEUED" and not failed.unknown_submission
    assert failed.slot is not None and failed.slot_generation is not None
    # Stale sweep snapshot: FAILED and still holding the pre-retry generation.
    store.slots[failed.slot] = (job_id, failed.slot_generation)
    stale = failed
    provider.reject_with = None
    service.retry(job_id, "alice")
    process_job(service, job_id)
    active = service.owned(job_id, "alice")
    assert active.phase == "OCR" and active.slot is not None
    assert active.slot_generation is not None
    assert active.slot_generation != stale.slot_generation
    assert store.slots[active.slot] == (job_id, active.slot_generation)
    # Cleanup using the old FAILED snapshot must not delete the reacquired slot.
    assert stale.slot is not None and stale.slot_generation is not None
    store.release_slot(stale.id, stale.slot, stale.slot_generation)
    assert store.slots[active.slot] == (job_id, active.slot_generation)
    sibling = accept(service)
    process_job(service, sibling)
    assert service.owned(sibling, "alice").phase == "QUEUED"
    assert job_id in provider.started and sibling not in provider.started


def test_deadline_after_crash_retains_uncertain_capacity() -> None:
    service, store, _, provider = make_service()
    service.settings = service.settings.model_copy(
        update={"active_jobs": 1, "max_job_seconds": 300}
    )
    job_id = uncertain_after_accept_crash(service, store, provider)
    provider.state = "IN_PROGRESS"
    held = service.owned(job_id, "alice")
    assert held.slot is not None and held.slot_generation is not None
    held_slot, held_generation = held.slot, held.slot_generation
    occupied = dict(store.slots)
    # Past attempt deadline, still within the absolute six-day handle window.
    service.clock = lambda: 1_000_000 + 301
    process_job(service, job_id)
    failed = service.owned(job_id, "alice")
    assert failed.phase == "FAILED"
    assert failed.error_code == "JOB_DEADLINE"
    assert failed.unknown_submission
    assert failed.retry_phase == "SUBMITTING"
    assert failed.slot == held_slot and failed.slot_generation == held_generation
    assert store.slots == occupied
    service.dispatch_due()
    assert store.slots == occupied
    sibling = accept(service)
    process_job(service, sibling)
    assert service.owned(sibling, "alice").phase == "QUEUED"
    assert len(provider.started) == 1 and job_id in provider.started
    assert sibling not in provider.started


def test_heartbeat_failure_with_prior_uncertainty_retains_capacity() -> None:
    service, store, _, provider = make_service()
    job_id = uncertain_after_accept_crash(service, store, provider)
    provider.state = "IN_PROGRESS"
    held = service.owned(job_id, "alice")
    assert held.slot is not None and held.slot_generation is not None
    held_slot, held_generation = held.slot, held.slot_generation
    occupied = dict(store.slots)
    calls_before = provider.calls
    lease = store.claim(held, int(service.clock()), service.settings.lease_seconds)
    assert lease is not None

    def failing_heartbeat() -> None:
        raise AwsError("HEARTBEAT_REJECTED", False)

    try:
        service.process_claimed(held, lease, failing_heartbeat)
    finally:
        store.release(job_id, lease)

    assert provider.calls == calls_before
    failed = service.owned(job_id, "alice")
    assert failed.phase == "FAILED"
    assert failed.error_code == "HEARTBEAT_REJECTED"
    assert failed.unknown_submission
    assert failed.retry_phase == "SUBMITTING"
    assert failed.slot == held_slot and failed.slot_generation == held_generation
    assert store.slots == occupied
    service.dispatch_due()
    assert store.slots == occupied
    sibling = accept(service)
    process_job(service, sibling)
    assert service.owned(sibling, "alice").phase == "QUEUED"
    assert len(provider.started) == 1 and job_id in provider.started
    assert sibling not in provider.started


class Auth:
    def verify(self, token: str) -> str:
        if token not in {"alice", "bob"}:
            raise JobError("UNAUTHORIZED", 401)
        return token


def test_http_acceptance_auth_ownership_and_status_without_waiting_for_ocr() -> None:
    service, _, _, provider = make_service()
    app = FastAPI()
    app.state.document_service = service
    app.state.document_auth = Auth()
    app.include_router(router)
    install_errors(app)
    client = TestClient(app)
    alice = {"Authorization": "Bearer alice"}
    assert client.get("/api/v1/documents/jobs").status_code == 401
    response = client.post(
        "/api/v1/documents/uploads", headers=alice, json={"filename": "record.pdf", "size_bytes": 9}
    )
    assert response.status_code == 201
    job_id = response.json()["job_id"]
    assert client.post(f"/api/v1/documents/jobs/{job_id}/start", headers=alice).status_code == 202
    assert provider.calls == 0
    assert (
        client.get(
            f"/api/v1/documents/jobs/{job_id}", headers={"Authorization": "Bearer bob"}
        ).status_code
        == 404
    )
    assert client.get("/api/v1/documents/jobs", headers=alice).json()[0]["phase"] == "QUEUED"
    response = client.post(
        "/api/v1/documents/uploads",
        headers=alice,
        json={"filename": "a.pdf", "size_bytes": 9, "owner": "bob"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("state", ["SUCCEEDED", "PARTIAL_SUCCESS"])
def test_completed_warning_count_is_persisted_and_exposed_without_object_reads(
    state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, store, objects, provider = make_service()
    provider.state = state
    job_id = accept(service)
    process_job(service, job_id)
    ready(service, job_id)
    process_job(service, job_id)
    completed = service.owned(job_id, "alice")
    document = Document.model_validate_json(objects.read(completed.artifacts["document.json"]))
    assert completed.phase == document.status == state
    assert completed.warning_count == len(document.warnings) > 0
    assert Job.model_validate_json(store.rows[job_id]).warning_count == len(document.warnings)

    def forbidden_read(artifact: Artifact) -> bytes:
        pytest.fail("Status polling must not read object storage")

    monkeypatch.setattr(objects, "read", forbidden_read)
    app = FastAPI()
    app.state.document_service = service
    app.state.document_auth = Auth()
    app.include_router(router)
    install_errors(app)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer alice"}
        response = client.get(f"/api/v1/documents/jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        assert response.json()["warning_count"] == len(document.warnings)
        listed = client.get("/api/v1/documents/jobs", headers=headers)
        assert listed.status_code == 200
        assert listed.json()[0]["warning_count"] == len(document.warnings)
        assert "warnings" not in response.json()


def test_legacy_job_and_status_default_warning_count_to_zero() -> None:
    service, store, _, _ = make_service()
    job_id = accept(service)
    job = service.owned(job_id, "alice")
    store.rows[job_id] = job.model_dump_json(exclude={"warning_count"})
    restored = service.owned(job_id, "alice")
    assert restored.warning_count == JobStatus.from_job(restored).warning_count == 0
    legacy_status = JobStatus.from_job(restored).model_dump(exclude={"warning_count"})
    assert JobStatus.model_validate(legacy_status).warning_count == 0


def test_failed_notification_outbox_retries_and_preserves_terminal_state() -> None:
    service, _, _, provider = make_service()
    provider.state = "FAILED"
    job_id = accept(service)
    process_job(service, job_id)
    ready(service, job_id)
    process_job(service, job_id)
    queue = cast(QueueFake, service.queue)
    assert service.owned(job_id, "alice").phase == "FAILED" and not queue.dead
    service.dispatch_due()
    assert queue.dead == [(job_id, "TEXTRACT_FAILED")]
    service.dispatch_due()
    assert len(queue.dead) == 1 and service.owned(job_id, "alice").failure_notified


def test_attempt_deadline_is_persisted_and_does_not_resubmit() -> None:
    service, store, _, provider = make_service()
    job_id = accept(service)
    process_job(service, job_id)
    ready(service, job_id)
    service.clock = lambda: 1_100_000
    process_job(service, job_id)
    failed = service.owned(job_id, "alice")
    assert failed.phase == "FAILED" and failed.error_code == "JOB_DEADLINE"
    assert failed.retry_phase == "OCR" and provider.calls == 1 and store.slots
    service.retry(job_id, "alice")
    process_job(service, job_id)
    assert service.owned(job_id, "alice").phase == "SUCCEEDED" and provider.calls == 1


def test_enabled_lifespan_wires_ui_api_and_isolation_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.document_jobs.settings import DocumentSettings
    from app.main import create_app
    from app.settings import Settings

    service, _, _, provider = make_service()

    def build(config: DocumentSettings) -> JobService:
        assert config.bucket == service.settings.bucket
        return service

    def load() -> DocumentSettings:
        return service.settings

    def build_review(config: DocumentSettings, jobs: object) -> object:
        assert config.bucket == service.settings.bucket
        assert jobs is service.store
        return object()

    monkeypatch.setattr("app.document_jobs.composition.build_service", build)
    monkeypatch.setattr("app.document_jobs.settings.load_document_settings", load)
    monkeypatch.setattr("app.document_review.composition.build_review_service", build_review)
    app = create_app(Settings(document_conversion_enabled=True))
    with TestClient(app) as client:
        app.state.document_auth = Auth()
        page = client.get("/documents")
        assert page.status_code == 200 and 'id="files"' in page.text
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert page.headers["cache-control"] == "no-store"
        assert client.get("/documents/config").json()["max_pdf_bytes"] == 25 * 1024 * 1024
        assert client.get("/api/v1/documents/jobs").status_code == 401
        assert client.get("/health").json() == {"status": "ok"}
        assert provider.calls == 0

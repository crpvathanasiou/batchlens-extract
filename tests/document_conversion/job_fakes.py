"""Faithful local CAS/lease and versioned-object fakes for job-boundary tests."""

import json
from collections.abc import Iterator
from threading import RLock
from typing import Any
from uuid import uuid4

from app.document_conversion.aws import AwsError, S3Source, TextractAdapter
from app.document_jobs.contracts import ACTIVE, Artifact, Job, UploadGrant
from app.document_jobs.service import JobService
from app.document_jobs.settings import DocumentSettings
from tests.document_conversion.fixtures import layout_fixture


class WorkerCrash(BaseException):
    """Abrupt worker death; bypasses Exception handlers in the job service."""


def settings() -> DocumentSettings:
    return DocumentSettings(
        region="eu-west-1",
        bucket="test-bucket",
        table="jobs",
        queue_url="queue",
        dlq_url="dlq",
        cognito_pool_id="pool",
        cognito_client_id="client",
        origin="https://example.test",
    )


class Store:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}  # Serialize on every commit; no shared Job object state.
        self.leases: dict[str, tuple[str, int]] = {}
        self.slots: dict[int, tuple[str, str]] = {}  # slot -> (job_id, generation)
        self.lock = RLock()

    def create(self, job: Job) -> None:
        with self.lock:
            assert job.id not in self.rows
            self.rows[job.id] = job.model_dump_json()

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            raw = self.rows.get(job_id)
            return Job.model_validate_json(raw) if raw else None

    def replace(self, job: Job, previous_revision: int, lease: str | None = None) -> bool:
        with self.lock:
            old = self.get(job.id)
            actual = self.leases.get(job.id)
            if old is None or old.revision != previous_revision:
                return False
            if (lease and (not actual or actual[0] != lease)) or (not lease and actual):
                return False
            self.rows[job.id] = job.model_dump_json()
            return True

    def due(self, now: int) -> Iterator[Job]:
        for raw in list(self.rows.values()):
            job = Job.model_validate_json(raw)
            if job.phase in ACTIVE and job.next_due <= now:
                yield job

    def owned(self, owner: str) -> Iterator[Job]:
        for raw in list(self.rows.values()):
            job = Job.model_validate_json(raw)
            if job.owner == owner:
                yield job

    def settled(self) -> Iterator[Job]:
        for raw in list(self.rows.values()):
            job = Job.model_validate_json(raw)
            if job.phase in {"SUCCEEDED", "PARTIAL_SUCCESS", "FAILED"}:
                yield job

    def claim(self, job: Job, now: int, lease_seconds: int) -> str | None:
        with self.lock:
            latest = self.get(job.id)
            lease = self.leases.get(job.id)
            if latest is None or latest.revision != job.revision or (lease and lease[1] >= now):
                return None
            token = uuid4().hex
            self.leases[job.id] = (token, now + lease_seconds)
            return token

    def heartbeat(self, job_id: str, lease: str, until: int) -> bool:
        with self.lock:
            current = self.leases.get(job_id)
            if current is None or current[0] != lease:
                return False
            self.leases[job_id] = (lease, until)
            return True

    def release(self, job_id: str, lease: str) -> None:
        with self.lock:
            if self.leases.get(job_id, (None, 0))[0] == lease:
                del self.leases[job_id]

    def acquire_slot(self, job_id: str, limit: int) -> tuple[int, str] | None:
        with self.lock:
            for slot, (current, _generation) in list(self.slots.items()):
                if current == job_id:
                    generation = uuid4().hex
                    self.slots[slot] = (job_id, generation)
                    return slot, generation
            for slot in range(limit):
                if slot not in self.slots:
                    generation = uuid4().hex
                    self.slots[slot] = (job_id, generation)
                    return slot, generation
            return None

    def release_slot(self, job_id: str, slot: int, generation: str) -> None:
        with self.lock:
            current = self.slots.get(slot)
            if current == (job_id, generation):
                del self.slots[slot]


class Objects:
    def __init__(self) -> None:
        self.version = "version-one"
        self.data: dict[tuple[str, str], bytes] = {}

    def grant(self, job: Job) -> UploadGrant:
        return UploadGrant(
            job_id=job.id, url="https://s3.test/", fields={"key": job.source.key}, expires_in=300
        )

    def verify(self, job: Job) -> S3Source:
        return job.source.model_copy(update={"version": self.version})

    def put(self, job_id: str, name: str, body: bytes, content_type: str) -> Artifact:
        artifact = Artifact(
            key=f"results/{job_id}/{name}", version=uuid4().hex, content_type=content_type
        )
        self.data[(artifact.key, artifact.version)] = body
        return artifact

    def read(self, artifact: Artifact) -> bytes:
        return self.data[(artifact.key, artifact.version)]

    def download(self, artifact: Artifact, filename: str) -> str:
        return f"https://download.test/{artifact.key}?version={artifact.version}"


class QueueFake:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.dead: list[tuple[str, str]] = []
        self.fail = False

    def send(self, job_id: str) -> None:
        if self.fail:
            raise AwsError("AWS_TRANSPORT_ERROR", True)
        self.messages.append(job_id)

    def dead_letter(self, job_id: str, code: str) -> None:
        self.dead.append((job_id, code))


class Provider:
    def __init__(self) -> None:
        self.started: dict[str, str] = {}
        self.calls = 0
        self.state = "SUCCEEDED"
        self.fail_after_submit = False
        self.crash_after_accept = False
        self.reject_with: str | None = None
        self.response = layout_fixture()
        self.sources: dict[str, Any] = {}

    def start_document_analysis(self, **params: Any) -> dict[str, str]:
        self.calls += 1
        if self.reject_with:
            raise AwsError(self.reject_with, False)
        token: str = params["ClientRequestToken"]
        self.started.setdefault(token, "textract-" + token)
        self.sources[token] = params["DocumentLocation"]
        if self.crash_after_accept:
            self.crash_after_accept = False
            raise WorkerCrash()
        if self.fail_after_submit:
            self.fail_after_submit = False
            raise AwsError("AWS_TRANSPORT_ERROR", True)
        return {"JobId": self.started[token]}

    def get_document_analysis(self, **params: Any) -> dict[str, Any]:
        response: dict[str, Any] = json.loads(json.dumps(self.response))
        response["JobStatus"] = self.state
        return response


def make_service() -> tuple[JobService, Store, Objects, Provider]:
    store, objects, provider = Store(), Objects(), Provider()
    service = JobService(
        store,
        objects,
        QueueFake(),
        TextractAdapter(provider, "eu-west-1"),
        settings(),
        clock=lambda: 1_000_000,
    )
    return service, store, objects, provider

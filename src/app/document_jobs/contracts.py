"""Application job state, authenticated ownership, and persistence boundaries."""

from collections.abc import Iterator
from typing import Literal, Protocol

from pydantic import Field

from app.document_conversion.aws import JobHandle, S3Source
from app.document_conversion.contracts import Model

Phase = Literal[
    "UPLOADING",
    "QUEUED",
    "SUBMITTING",
    "OCR",
    "COLLECTING",
    "RENDERING",
    "SUCCEEDED",
    "PARTIAL_SUCCESS",
    "FAILED",
]
ACTIVE: frozenset[str] = frozenset({"QUEUED", "SUBMITTING", "OCR", "COLLECTING", "RENDERING"})
TERMINAL: frozenset[str] = frozenset({"SUCCEEDED", "PARTIAL_SUCCESS", "FAILED"})


class Artifact(Model):
    key: str
    version: str
    content_type: str


class Job(Model):
    id: str
    owner: str
    filename: str
    phase: Phase = "UPLOADING"
    revision: int = 0
    created_at: int
    updated_at: int
    expires_at: int
    next_due: int = 0
    expected_bytes: int
    source: S3Source
    handle: JobHandle | None = None
    slot: int | None = None
    # Ownership generation for the durable slot row; required for conditional release.
    slot_generation: str | None = None
    ocr_finished: bool = False
    # True once a StartDocumentAnalysis attempt may have been accepted without a handle.
    # Set before the external call; a later definitive rejection must not clear prior uncertainty.
    unknown_submission: bool = False
    failure_notified: bool = False
    attempt_started_at: int = 0
    failures: int = 0
    error_code: str | None = None
    retry_phase: Phase | None = None
    pages_available: int | None = None
    warning_count: int = Field(default=0, ge=0)
    raw: Artifact | None = None
    artifacts: dict[str, Artifact] = Field(default_factory=dict)


class JobStatus(Model):
    id: str
    filename: str
    phase: Phase
    pages_available: int | None = None
    warning_count: int = Field(default=0, ge=0)
    error_code: str | None = None
    artifacts: tuple[str, ...] = ()

    @classmethod
    def from_job(cls, job: Job) -> "JobStatus":
        return cls(
            id=job.id,
            filename=job.filename,
            phase=job.phase,
            pages_available=job.pages_available,
            warning_count=job.warning_count,
            error_code=job.error_code,
            artifacts=tuple(sorted(job.artifacts)),
        )


class JobError(RuntimeError):
    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class JobStore(Protocol):
    def create(self, job: Job) -> None: ...
    def get(self, job_id: str) -> Job | None: ...
    def replace(self, job: Job, previous_revision: int, lease: str | None = None) -> bool: ...
    def due(self, now: int) -> Iterator[Job]: ...
    def settled(self) -> Iterator[Job]: ...
    def owned(self, owner: str) -> Iterator[Job]: ...
    def claim(self, job: Job, now: int, lease_seconds: int) -> str | None: ...
    def heartbeat(self, job_id: str, lease: str, until: int) -> bool: ...
    def release(self, job_id: str, lease: str) -> None: ...
    def acquire_slot(self, job_id: str, limit: int) -> tuple[int, str] | None: ...
    def release_slot(self, job_id: str, slot: int, generation: str) -> None: ...


class UploadGrant(Model):
    job_id: str
    url: str
    fields: dict[str, str]
    expires_in: int


class ObjectStore(Protocol):
    def grant(self, job: Job) -> UploadGrant: ...
    def verify(self, job: Job) -> S3Source: ...
    def put(self, job_id: str, name: str, body: bytes, content_type: str) -> Artifact: ...
    def read(self, artifact: Artifact) -> bytes: ...
    def download(self, artifact: Artifact, filename: str) -> str: ...


class Queue(Protocol):
    def send(self, job_id: str) -> None: ...
    def dead_letter(self, job_id: str, code: str) -> None: ...

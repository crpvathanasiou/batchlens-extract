"""Local persisted background jobs that invoke Stage 2 / L13 (U2.2).

One in-process service per data directory submits queued jobs, runs Stage 2 in a
background thread, and persists truthful status/progress as atomic JSON. Does not
create reviews, approve results, or expose an API.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.extraction_review.approved_documents import (
    ApprovedDocumentError,
    ApprovedDocumentsRegistry,
)
from app.extraction_review.contracts import (
    ExtractionReviewAction,
    PublishedManifestReference,
    action_to_preset,
)
from app.lexical_extraction.configuration import (
    ConfigurationError,
    EffectiveExecutionConfiguration,
    ExtractionRequest,
    InputPaths,
    OutputPaths,
    SelectionOverride,
    load_execution_configuration,
    resolve_components,
)
from app.lexical_extraction.contracts import (
    ExtractionOutcomeRecord,
    PublicationRecord,
    PublicationStatus,
    ReviewedHtmlV1Input,
    RunProvenance,
    SafeStructuredError,
)
from app.lexical_extraction.publication import (
    FilesystemEvidenceSink,
    PublicationError,
    PublicationResult,
    finalize_publication,
)
from app.lexical_extraction.runner import (
    LexicalRunnerError,
    LexicalRunResult,
    run_lexical_extraction,
)

JOB_SCHEMA_VERSION: Final = "batchlens.extraction-local-job.v1"
JOBS_DIR_NAME: Final = "extraction-jobs"
RAW_RUNS_DIR_NAME: Final = "extraction-raw-runs"
_MAX_ERROR_MESSAGE: Final = 200
_LOCAL_JOB_ID_RE: Final = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

Stage2Execute: TypeAlias = Callable[
    [EffectiveExecutionConfiguration, FilesystemEvidenceSink],
    tuple[LexicalRunResult, PublicationResult],
]

_ACTIVE_SERVICES: dict[Path, LocalLexicalJobService] = {}
_ACTIVE_LOCK = threading.Lock()


class LocalJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class LocalJobPhase(StrEnum):
    QUEUED = "queued"
    VALIDATING_DOCUMENT = "validating_document"
    RUNNING_EXTRACTION = "running_extraction"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class LocalLexicalJobNotFoundError(FileNotFoundError):
    """No persisted local lexical job exists for the requested ID."""


class LocalLexicalJobServiceAlreadyActiveError(RuntimeError):
    """Another in-process service already owns this data directory."""


class LocalLexicalJobServiceBusyError(RuntimeError):
    """Close refused because one or more worker threads are still alive."""


class LocalLexicalJobModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LocalLexicalJob(LocalLexicalJobModel):
    """Latest persisted state for one local Stage 2 background job."""

    schema_version: Literal["batchlens.extraction-local-job.v1"] = JOB_SCHEMA_VERSION
    local_job_id: Annotated[str, Field(pattern=_LOCAL_JOB_ID_RE.pattern)]
    job_id: Annotated[str, Field(min_length=1)]
    review_revision_id: Annotated[str, Field(min_length=1)]
    action: ExtractionReviewAction
    fuzzy_enabled: StrictBool = False
    status: LocalJobStatus
    phase: LocalJobPhase
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reviewed_html: ReviewedHtmlV1Input | None = None
    run: RunProvenance | None = None
    extraction: ExtractionOutcomeRecord | None = None
    publication: PublicationRecord | None = None
    raw_run_relative_dir: Annotated[str, Field(min_length=1)] | None = None
    published_manifest: PublishedManifestReference | None = None
    error: SafeStructuredError | None = None


class LocalLexicalJobService:
    """Single-local-process owner of background lexical jobs under one data directory."""

    def __init__(
        self,
        data_dir: Path,
        *,
        execute_stage2: Stage2Execute | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        resolved = data_dir.expanduser().resolve()
        with _ACTIVE_LOCK:
            existing = _ACTIVE_SERVICES.get(resolved)
            if existing is not None and not existing._closed:
                raise LocalLexicalJobServiceAlreadyActiveError(
                    "a local lexical job service is already active for this data directory"
                )
            _ACTIVE_SERVICES[resolved] = self

        self._data_dir = resolved
        self._execute_stage2 = execute_stage2
        self._clock = clock or _utc_now
        self._closed = False
        self._lock = threading.RLock()
        self._execution_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._jobs_dir = self._data_dir / JOBS_DIR_NAME
        self._raw_runs_dir = self._data_dir / RAW_RUNS_DIR_NAME
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        self._raw_runs_dir.mkdir(parents=True, exist_ok=True)
        self._interrupt_abandoned_jobs()

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def jobs_dir(self) -> Path:
        return self._jobs_dir

    @property
    def raw_runs_dir(self) -> Path:
        return self._raw_runs_dir

    def close(self) -> None:
        with self._lock:
            alive = [thread for thread in self._threads if thread.is_alive()]
            if alive:
                raise LocalLexicalJobServiceBusyError(
                    "cannot close local lexical job service while worker threads are active"
                )
        with _ACTIVE_LOCK:
            if _ACTIVE_SERVICES.get(self._data_dir) is self:
                del _ACTIVE_SERVICES[self._data_dir]
            self._closed = True

    def __enter__(self) -> LocalLexicalJobService:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def submit(
        self,
        *,
        approved_documents_root: Path,
        job_id: str,
        review_revision_id: str,
        config_path: Path,
        action: ExtractionReviewAction,
        fuzzy_enabled: bool = False,
    ) -> LocalLexicalJob:
        if self._closed:
            raise RuntimeError("local lexical job service is closed")
        if type(fuzzy_enabled) is not bool:
            raise TypeError("fuzzy_enabled must be a strict bool")

        now = self._clock()
        local_job_id = str(uuid.uuid4())
        job = LocalLexicalJob(
            local_job_id=local_job_id,
            job_id=job_id,
            review_revision_id=review_revision_id,
            action=action,
            fuzzy_enabled=fuzzy_enabled,
            status=LocalJobStatus.QUEUED,
            phase=LocalJobPhase.QUEUED,
            submitted_at=now,
        )
        self._write_job(job)

        thread = threading.Thread(
            target=self._run_job,
            name=f"local-lexical-job-{local_job_id}",
            args=(
                local_job_id,
                Path(approved_documents_root),
                Path(config_path),
            ),
            daemon=True,
        )
        with self._lock:
            self._threads.append(thread)
        thread.start()
        return job

    def get_job(self, local_job_id: str) -> LocalLexicalJob:
        if not _LOCAL_JOB_ID_RE.fullmatch(local_job_id):
            raise LocalLexicalJobNotFoundError(
                f"local lexical job not found for id={local_job_id!r}"
            )
        path = self._job_path(local_job_id)
        if not path.is_file():
            raise LocalLexicalJobNotFoundError(
                f"local lexical job not found for id={local_job_id!r}"
            )
        return self._read_job(path)

    def _run_job(
        self,
        local_job_id: str,
        approved_documents_root: Path,
        config_path: Path,
    ) -> None:
        # Remain queued until this thread owns the single per-service execution lock.
        self._execution_lock.acquire()
        try:
            try:
                job = self.get_job(local_job_id)
                started = self._clock()
                job = self._replace(
                    job,
                    status=LocalJobStatus.RUNNING,
                    phase=LocalJobPhase.VALIDATING_DOCUMENT,
                    started_at=started,
                )
                self._write_job(job)

                selected = ApprovedDocumentsRegistry(approved_documents_root).select(
                    job.job_id,
                    job.review_revision_id,
                )
                job = self._replace(
                    job,
                    reviewed_html=selected.reviewed_html,
                    phase=LocalJobPhase.RUNNING_EXTRACTION,
                )
                self._write_job(job)

                config = _build_effective_config(
                    config_path=config_path,
                    reviewed_html_path=selected.html_path,
                    action=job.action,
                    fuzzy_enabled=job.fuzzy_enabled,
                    output_directory=self._raw_runs_dir,
                )
                sink = FilesystemEvidenceSink(
                    self._raw_runs_dir,
                    snapshot_directory=config.knowledge.snapshot_directory,
                )
                run_result, publication_result = self._invoke_stage2(
                    local_job_id,
                    config,
                    sink,
                )
                self._finalize_from_stage2(
                    local_job_id,
                    run_result,
                    publication_result,
                    sink,
                )
            except Exception as exc:
                self._fail_job(local_job_id, _map_failure(exc))
        finally:
            self._execution_lock.release()

    def _invoke_stage2(
        self,
        local_job_id: str,
        config: EffectiveExecutionConfiguration,
        sink: FilesystemEvidenceSink,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        if self._execute_stage2 is not None:
            return self._execute_stage2(config, sink)

        run_result = run_lexical_extraction(config, sink)
        job = self.get_job(local_job_id)
        job = self._replace(job, phase=LocalJobPhase.PUBLISHING)
        self._write_job(job)
        return run_result, finalize_publication(sink, run_result)

    def _finalize_from_stage2(
        self,
        local_job_id: str,
        run_result: LexicalRunResult,
        publication_result: PublicationResult,
        sink: FilesystemEvidenceSink,
    ) -> None:
        job = self.get_job(local_job_id)
        raw_relative = _raw_run_relative(sink, self._raw_runs_dir)
        published_manifest: PublishedManifestReference | None = None
        error = publication_result.error

        if (
            publication_result.publication.status is PublicationStatus.COMPLETED
            and publication_result.publication.final_manifest is not None
            and publication_result.manifest_path is not None
        ):
            digest = _sha256_file(publication_result.manifest_path)
            published_manifest = PublishedManifestReference(
                manifest_id=publication_result.publication.final_manifest.manifest_id,
                manifest_sha256=digest,
            )
            finished = self._clock()
            job = self._replace(
                job,
                status=LocalJobStatus.COMPLETED,
                phase=LocalJobPhase.COMPLETED,
                finished_at=finished,
                run=run_result.provenance,
                extraction=run_result.extraction,
                publication=publication_result.publication,
                raw_run_relative_dir=raw_relative,
                published_manifest=published_manifest,
                error=None,
            )
            self._write_job(job)
            return

        if error is None:
            if run_result.run_error is not None:
                error = run_result.run_error
                error_kind: Literal["runner", "publication"] = "runner"
            elif run_result.pre_validation is not None:
                error = run_result.pre_validation.error
                error_kind = "runner"
            else:
                error = _safe_error(
                    "STAGE2_PUBLICATION_FAILED",
                    _FIXED_PUBLICATION_MESSAGE,
                )
                error_kind = "publication"
        else:
            error_kind = "publication"
        finished = self._clock()
        job = self._replace(
            job,
            status=LocalJobStatus.FAILED,
            phase=LocalJobPhase.FAILED,
            finished_at=finished,
            run=run_result.provenance,
            extraction=run_result.extraction,
            publication=publication_result.publication,
            raw_run_relative_dir=raw_relative,
            published_manifest=None,
            error=_sanitize_structured_error(error, kind=error_kind),
        )
        self._write_job(job)

    def _fail_job(self, local_job_id: str, error: SafeStructuredError) -> None:
        try:
            job = self.get_job(local_job_id)
        except LocalLexicalJobNotFoundError:
            return
        if job.status in {
            LocalJobStatus.COMPLETED,
            LocalJobStatus.FAILED,
            LocalJobStatus.INTERRUPTED,
        }:
            return
        job = self._replace(
            job,
            status=LocalJobStatus.FAILED,
            phase=LocalJobPhase.FAILED,
            finished_at=self._clock(),
            started_at=job.started_at or self._clock(),
            error=error,
        )
        self._write_job(job)

    def _interrupt_abandoned_jobs(self) -> None:
        if not self._jobs_dir.is_dir():
            return
        now = self._clock()
        interruption = _safe_error(
            "JOB_INTERRUPTED",
            _FIXED_INTERRUPT_MESSAGE,
        )
        for path in sorted(self._jobs_dir.glob("*.json")):
            if path.name.startswith("."):
                continue
            try:
                job = self._read_job(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if job.status not in {LocalJobStatus.QUEUED, LocalJobStatus.RUNNING}:
                continue
            updated = self._replace(
                job,
                status=LocalJobStatus.INTERRUPTED,
                phase=LocalJobPhase.INTERRUPTED,
                finished_at=now,
                started_at=job.started_at or now,
                error=interruption,
            )
            self._write_job(updated)

    def _job_path(self, local_job_id: str) -> Path:
        return self._jobs_dir / f"{local_job_id}.json"

    def _write_job(self, job: LocalLexicalJob) -> None:
        path = self._job_path(job.local_job_id)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
        payload = job.model_dump(mode="json")
        body = (
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
            + "\n"
        ).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with temporary.open("xb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _read_job(self, path: Path) -> LocalLexicalJob:
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
        return LocalLexicalJob.model_validate(payload)

    @staticmethod
    def _replace(job: LocalLexicalJob, **changes: object) -> LocalLexicalJob:
        return job.model_copy(update=changes)


def _build_effective_config(
    *,
    config_path: Path,
    reviewed_html_path: Path,
    action: ExtractionReviewAction,
    fuzzy_enabled: bool,
    output_directory: Path,
) -> EffectiveExecutionConfiguration:
    preset = action_to_preset(action)
    base = load_execution_configuration(
        config_path,
        overrides=SelectionOverride(
            presets=(preset,),
            components=(),
            fuzzy_enabled=fuzzy_enabled,
        ),
    )
    resolved = resolve_components((preset,), ())
    return EffectiveExecutionConfiguration(
        schema_version=base.schema_version,
        input=InputPaths(reviewed_html_path=reviewed_html_path.resolve()),
        knowledge=base.knowledge,
        output=OutputPaths(directory=output_directory.resolve()),
        extraction=ExtractionRequest(
            presets=(preset,),
            components=(),
            fuzzy_enabled=fuzzy_enabled,
        ),
        resolved_components=resolved,
        resources=base.resources,
    )


def _raw_run_relative(
    sink: FilesystemEvidenceSink,
    raw_runs_dir: Path,
) -> str | None:
    """Return the run directory name only when it exists directly under raw_runs_dir."""

    candidate = sink.run_directory
    if candidate is None:
        return None
    try:
        resolved = candidate.resolve()
        root = raw_runs_dir.resolve()
        if not resolved.is_dir():
            return None
        if resolved.parent != root:
            return None
        name = resolved.name
        if not name or name in {".", ".."}:
            return None
        return name
    except OSError:
        return None


_FIXED_SELECTION_MESSAGES: Final[dict[str, str]] = {
    "DOCUMENT_NOT_FOUND": "approved document was not found",
    "PATH_ESCAPE": "approved document path is not allowed",
    "IDENTITY_MISMATCH": "folder identity does not match reviewed HTML provenance",
    "INVALID_REVIEWED_HTML": "reviewed HTML failed Stage 2 validation",
    "INVALID_ARGUMENT": "approved document request is invalid",
    "MALFORMED_LAYOUT": "approved document layout is invalid",
}
_FIXED_SELECTION_FALLBACK: Final = "approved document selection failed"
_FIXED_CONFIGURATION_MESSAGE: Final = "execution configuration is invalid"
_FIXED_RUNNER_MESSAGE: Final = "Stage 2 extraction failed"
_FIXED_PUBLICATION_MESSAGE: Final = "Stage 2 publication failed"
_FIXED_IO_MESSAGE: Final = "local job I/O failed"
_FIXED_UNEXPECTED_MESSAGE: Final = "local job failed unexpectedly"
_FIXED_INTERRUPT_MESSAGE: Final = "local lexical job was interrupted by service restart"


def _map_failure(exc: BaseException) -> SafeStructuredError:
    if isinstance(exc, ApprovedDocumentError):
        message = _FIXED_SELECTION_MESSAGES.get(exc.code, _FIXED_SELECTION_FALLBACK)
        return _safe_error(exc.code, message)
    if isinstance(exc, ConfigurationError):
        return _safe_error("CONFIGURATION_ERROR", _FIXED_CONFIGURATION_MESSAGE)
    if isinstance(exc, LexicalRunnerError):
        return _safe_error(exc.code, _FIXED_RUNNER_MESSAGE)
    if isinstance(exc, PublicationError):
        return _safe_error(exc.code, _FIXED_PUBLICATION_MESSAGE)
    if isinstance(exc, OSError):
        return _safe_error("IO_ERROR", _FIXED_IO_MESSAGE)
    return _safe_error("UNEXPECTED_FAILURE", _FIXED_UNEXPECTED_MESSAGE)


def _sanitize_structured_error(
    error: SafeStructuredError,
    *,
    kind: Literal["selection", "runner", "publication", "unexpected"],
) -> SafeStructuredError:
    if kind == "selection":
        message = _FIXED_SELECTION_MESSAGES.get(error.code, _FIXED_SELECTION_FALLBACK)
    elif kind == "runner":
        message = _FIXED_RUNNER_MESSAGE
    elif kind == "publication":
        message = _FIXED_PUBLICATION_MESSAGE
    else:
        message = _FIXED_UNEXPECTED_MESSAGE
    return SafeStructuredError(
        code=error.code,
        message=message,
        component=error.component,
        retryable=False,
    )


def _safe_error(code: str, message: str) -> SafeStructuredError:
    return SafeStructuredError(
        code=code,
        message=_bounded_message(message),
        component=None,
        retryable=False,
    )


def _bounded_message(message: str) -> str:
    if 1 <= len(message) <= _MAX_ERROR_MESSAGE:
        return message
    if not message:
        return _FIXED_UNEXPECTED_MESSAGE
    return message[: _MAX_ERROR_MESSAGE - 3] + "..."


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65_536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)

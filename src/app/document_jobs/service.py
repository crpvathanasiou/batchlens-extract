"""Short request operations and resumable worker steps; no framework imports."""

import json
import logging
import time
from collections.abc import Callable
from uuid import uuid4

from app.document_conversion import ConversionError, ConversionLimits, convert_textract
from app.document_conversion.aws import AwsError, S3Source, TextractAdapter
from app.document_conversion.html import render_document, render_pages
from app.document_jobs.contracts import (
    ACTIVE,
    TERMINAL,
    Job,
    JobError,
    JobStatus,
    JobStore,
    ObjectStore,
    Queue,
    UploadGrant,
)
from app.document_jobs.settings import DocumentSettings

logger = logging.getLogger("app.document_jobs")


class JobService:
    def __init__(
        self,
        store: JobStore,
        objects: ObjectStore,
        queue: Queue,
        textract: TextractAdapter,
        settings: DocumentSettings,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.objects = objects
        self.queue = queue
        self.textract = textract
        self.settings = settings
        self.clock = clock

    def owned(self, job_id: str, owner: str) -> Job:
        job = self.store.get(job_id)
        if job is None or job.owner != owner:
            raise JobError("JOB_NOT_FOUND", 404)
        return job

    def initiate(self, owner: str, filename: str, size: int) -> UploadGrant:
        if not filename.lower().endswith(".pdf") or not 5 <= size <= self.settings.max_pdf_bytes:
            raise JobError("PDF_NAME_OR_SIZE_INVALID", 422)
        # Display-only filename; the key and owner always originate on the server.
        filename = filename.replace("\\", "/").split("/")[-1][:180]
        now = int(self.clock())
        job_id = uuid4().hex
        job = Job(
            id=job_id,
            owner=owner,
            filename=filename,
            expected_bytes=size,
            created_at=now,
            updated_at=now,
            expires_at=now + self.settings.retention_days * 86400,
            source=S3Source(
                bucket=self.settings.bucket,
                region=self.settings.region,
                key=f"{self.settings.prefix}/incoming/{job_id}/source.pdf",
            ),
        )
        self.store.create(job)
        return self.objects.grant(job)

    def save(self, job: Job, lease: str | None = None) -> Job:
        updated = job.model_copy(
            update={"revision": job.revision + 1, "updated_at": int(self.clock())}
        )
        if not self.store.replace(updated, job.revision, lease):
            raise JobError("STATE_CONFLICT")
        return updated

    def _wake(self, job_id: str) -> None:
        try:
            self.queue.send(job_id)
        except AwsError:
            # Persisted due jobs are swept by every worker; queue send is not a commit.
            logger.warning("enqueue_deferred job_id=%s", job_id)

    def start(self, job_id: str, owner: str) -> JobStatus:
        job = self.owned(job_id, owner)
        if job.phase != "UPLOADING":
            return JobStatus.from_job(job)
        if int(self.clock()) > job.created_at + 3600:
            raise JobError("UPLOAD_ACCEPTANCE_EXPIRED", 410)
        source = self.objects.verify(job)
        try:
            job = self.save(
                job.model_copy(
                    update={
                        "source": source,
                        "phase": "QUEUED",
                        "attempt_started_at": int(self.clock()),
                        "next_due": int(self.clock()),
                    }
                )
            )
        except JobError as error:
            latest = self.owned(job_id, owner)
            if latest.phase == "UPLOADING":
                raise error
            job = latest
        self._wake(job.id)
        return JobStatus.from_job(job)

    def retry(self, job_id: str, owner: str) -> JobStatus:
        job = self.owned(job_id, owner)
        if job.phase != "FAILED" or job.retry_phase is None:
            raise JobError("JOB_NOT_RESUMABLE")
        # Textract request tokens and results have a 7-day lifetime. Keep a safety margin.
        if int(self.clock()) - job.created_at > 6 * 86400:
            raise JobError("HANDLE_TOO_OLD_CREATE_NEW_JOB", 410)
        job = self.save(
            job.model_copy(
                update={
                    "phase": job.retry_phase,
                    "retry_phase": None,
                    "failures": 0,
                    "error_code": None,
                    "attempt_started_at": int(self.clock()),
                    "next_due": int(self.clock()),
                }
            )
        )
        self._wake(job.id)
        return JobStatus.from_job(job)

    def download(self, job_id: str, owner: str, name: str) -> str:
        job = self.owned(job_id, owner)
        if job.phase not in {"SUCCEEDED", "PARTIAL_SUCCESS"} or name not in job.artifacts:
            raise JobError("ARTIFACT_NOT_AVAILABLE", 404)
        return self.objects.download(job.artifacts[name], name)

    def dispatch_due(self) -> int:
        for settled in self.store.settled():
            if self._slot_releasable(settled):
                self._release_slot(settled)
            if settled.phase == "FAILED" and not settled.failure_notified:
                try:
                    self.queue.dead_letter(settled.id, settled.error_code or "JOB_FAILED")
                    self.save(settled.model_copy(update={"failure_notified": True}))
                except (AwsError, JobError):
                    logger.warning("failure_notification_deferred job_id=%s", settled.id)
        count = 0
        for job in self.store.due(int(self.clock())):
            self._wake(job.id)
            count += 1
            if count >= 100:
                break
        return count

    def _defer(self, job: Job, lease: str, seconds: int | None = None) -> Job:
        return self.save(
            job.model_copy(
                update={
                    "next_due": int(self.clock()) + (seconds or self.settings.poll_seconds),
                }
            ),
            lease,
        )

    def _release_slot(self, job: Job) -> None:
        if job.slot is not None and job.slot_generation is not None:
            self.store.release_slot(job.id, job.slot, job.slot_generation)

    def _slot_releasable(self, job: Job) -> bool:
        if job.ocr_finished:
            return True
        # Definitive submission rejection: no handle and no prior uncertain submit.
        return (
            job.phase == "FAILED"
            and job.handle is None
            and not job.unknown_submission
            and job.slot is not None
        )

    def _uncertain_submission(
        self, prior_uncertain: bool, job: Job, error: Exception, known: bool
    ) -> bool:
        # prior_uncertain is uncertainty before this turn's pre-call mark. Job.unknown_submission
        # alone is not enough: it is set before StartDocumentAnalysis for crash durability.
        if prior_uncertain:
            return True
        if job.phase != "SUBMITTING" or job.handle is not None:
            return False
        if not known:
            return True
        return isinstance(error, AwsError) and error.retryable

    def process_claimed(self, job: Job, lease: str, heartbeat: Callable[[], None]) -> None:
        """One bounded scheduling turn. The runtime maintains a renewing lease."""
        prior_uncertain = job.unknown_submission
        try:
            if job.phase in TERMINAL:
                if self._slot_releasable(job):
                    self._release_slot(job)
                return
            if job.phase not in ACTIVE:
                return
            # Retry grants another bounded recovery window through attempt_started_at, while
            # the absolute six-day handle limit still forbids accidental resubmission.
            if int(self.clock()) - job.created_at > 6 * 86400:
                raise AwsError("HANDLE_EXPIRED")
            if int(self.clock()) - job.attempt_started_at > self.settings.max_job_seconds:
                raise AwsError("JOB_DEADLINE")
            if job.phase == "QUEUED":
                acquired = self.store.acquire_slot(job.id, self.settings.active_jobs)
                if acquired is None:
                    self._defer(job, lease)
                    return
                slot, generation = acquired
                job = self.save(
                    job.model_copy(
                        update={
                            "slot": slot,
                            "slot_generation": generation,
                            "phase": "SUBMITTING",
                        }
                    ),
                    lease,
                )
            if job.phase == "SUBMITTING":
                heartbeat()
                # Persist uncertainty before the external call so a crash after acceptance
                # cannot look like a clean initial rejection.
                prior_uncertain = job.unknown_submission
                if not prior_uncertain:
                    job = self.save(job.model_copy(update={"unknown_submission": True}), lease)
                handle = self.textract.submit(job.source, job.id)
                job = self.save(
                    job.model_copy(update={"handle": handle, "phase": "OCR", "failures": 0}), lease
                )
                self._defer(job, lease)
                return
            if job.phase == "OCR":
                if job.handle is None:
                    raise JobError("PERSISTED_HANDLE_MISSING")
                check = self.textract.check(job.handle)
                job = job.model_copy(update={"pages_available": check.pages})
                if check.status == "IN_PROGRESS":
                    self._defer(job, lease)
                    return
                if check.status == "FAILED":
                    job = self.save(
                        job.model_copy(
                            update={
                                "phase": "FAILED",
                                "error_code": "TEXTRACT_FAILED",
                                "ocr_finished": True,
                            }
                        ),
                        lease,
                    )
                    self._release_slot(job)
                    return
                job = self.save(
                    job.model_copy(
                        update={"phase": "COLLECTING", "failures": 0, "ocr_finished": True}
                    ),
                    lease,
                )
            if job.phase == "COLLECTING":
                if job.handle is None:
                    raise JobError("PERSISTED_HANDLE_MISSING")
                result = self.textract.collect(job.handle, heartbeat)
                data = json.dumps(result.raw, ensure_ascii=False, separators=(",", ":")).encode()
                raw = self.objects.put(job.id, "textract.json", data, "application/json")
                job = self.save(
                    job.model_copy(update={"raw": raw, "phase": "RENDERING", "failures": 0}), lease
                )
            if job.phase == "RENDERING":
                if job.raw is None:
                    raise JobError("PERSISTED_RAW_MISSING")
                heartbeat()
                document = convert_textract(
                    json.loads(self.objects.read(job.raw)),
                    job.source.document_source(),
                    ConversionLimits(
                        max_blocks=self.settings.max_blocks, max_pages=self.settings.max_pages
                    ),
                )
                pages = render_pages(document, self.settings.page_workers)
                artifacts = {"textract.json": job.raw}
                artifacts["document.json"] = self.objects.put(
                    job.id,
                    "document.json",
                    document.model_dump_json(indent=2).encode(),
                    "application/json",
                )
                artifacts["document.html"] = self.objects.put(
                    job.id,
                    "document.html",
                    render_document(document).encode(),
                    "text/html",
                )
                for number, html in pages.items():
                    heartbeat()
                    name = f"page-{number:04d}.html"
                    artifacts[name] = self.objects.put(job.id, name, html.encode(), "text/html")
                job = self.save(
                    job.model_copy(
                        update={
                            "phase": document.status,
                            "artifacts": artifacts,
                            "pages_available": len(document.pages),
                            "warning_count": len(document.warnings),
                            "error_code": None,
                            "failures": 0,
                        }
                    ),
                    lease,
                )
                self._release_slot(job)
                logger.info(
                    "conversion_completed job_id=%s phase=%s pages=%s",
                    job.id,
                    job.phase,
                    job.pages_available,
                )
        except Exception as error:
            if isinstance(error, JobError) and error.code == "STATE_CONFLICT":
                return  # Lost lease/revision. Another execution owns the next transition.
            # Re-read persisted state: a failure after terminal commit must never undo it.
            latest = self.store.get(job.id)
            if latest is None or latest.phase in TERMINAL:
                raise
            known = isinstance(error, AwsError | ConversionError | JobError)
            code = str(error) if known else "WORKER_INTERNAL_ERROR"
            retryable = (isinstance(error, AwsError) and error.retryable) or not known
            failures = latest.failures + 1
            uncertain = self._uncertain_submission(prior_uncertain, latest, error, known)
            if retryable and failures < self.settings.max_failures:
                deferred = latest.model_copy(update={"failures": failures, "error_code": code})
                if uncertain:
                    deferred = deferred.model_copy(update={"unknown_submission": True})
                self._defer(deferred, lease, min(300, 10 * 2**failures))
                return
            # Unknown submission outcome retains the durable slot. Never overcommit OCR
            # by recycling it while a possibly-running AWS job is unresolved.
            # Definitive SUBMITTING rejection releases capacity and retries via QUEUED.
            if latest.phase == "SUBMITTING" and not uncertain:
                resumable: str | None = (
                    "QUEUED" if isinstance(error, AwsError) or not known else None
                )
            else:
                resumable = latest.phase if isinstance(error, AwsError) or not known else None
            failed_update: dict[str, object] = {
                "phase": "FAILED",
                "failures": failures,
                "error_code": code,
                "retry_phase": resumable,
                "failure_notified": False,
            }
            if uncertain:
                failed_update["unknown_submission"] = True
            elif latest.phase == "SUBMITTING":
                # Clear only the speculative pre-call mark for this rejected attempt.
                failed_update["unknown_submission"] = False
            failed = self.save(latest.model_copy(update=failed_update), lease)
            # Conversion failures occur after confirmed OCR completion.
            # Definitive submission rejection establishes that no OCR job started.
            if (latest.phase in {"COLLECTING", "RENDERING"} and resumable is None) or (
                latest.phase == "SUBMITTING" and not uncertain
            ):
                self._release_slot(failed)
            logger.warning("conversion_failed job_id=%s code=%s", job.id, code)

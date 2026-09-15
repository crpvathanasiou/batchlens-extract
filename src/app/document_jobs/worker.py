"""SQS delivery plus persisted-due recovery; bounded document threads and renewing leases."""

import logging
import signal
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from types import FrameType
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.document_conversion.aws import AwsError
from app.document_jobs.composition import build_service
from app.document_jobs.contracts import TERMINAL, JobError
from app.document_jobs.service import JobService
from app.document_jobs.settings import DocumentSettings, load_document_settings
from app.document_jobs.storage import SqsQueue
from app.logging_config import configure_logging

logger = logging.getLogger("app.document_jobs.worker")


class Delivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(pattern=r"^[a-f0-9]{32}$")


def process_job(service: JobService, job_id: str) -> None:
    job = service.store.get(job_id)
    if job is None:
        return
    now = int(service.clock())
    if job.next_due > now and job.phase not in TERMINAL:
        return
    lease = service.store.claim(job, now, service.settings.lease_seconds)
    if lease is None:
        return
    stop = threading.Event()
    lost = threading.Event()

    def beat() -> None:
        if lost.is_set() or not service.store.heartbeat(
            job_id,
            lease,
            int(service.clock()) + service.settings.lease_seconds,
        ):
            lost.set()
            raise JobError("STATE_CONFLICT")

    def renew() -> None:
        while not stop.wait(service.settings.lease_seconds / 3):
            try:
                beat()
            except (AwsError, JobError):
                lost.set()
                return

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        service.process_claimed(job, lease, beat)
    finally:
        stop.set()
        thread.join(timeout=1)
        service.store.release(job_id, lease)


def handle_message(
    service: JobService, sqs: Any, settings: DocumentSettings, message: dict[str, Any]
) -> None:
    try:
        delivery = Delivery.model_validate_json(message["Body"])
        process_job(service, delivery.job_id)
        sqs.delete_message(QueueUrl=settings.queue_url, ReceiptHandle=message["ReceiptHandle"])
    except ValidationError:
        # Leave poison messages for SQS redrive; never log the body.
        logger.warning("invalid_queue_message")
    except Exception as error:
        # Persisted due state, not this thread or message, is the recovery authority.
        logger.error("worker_turn_failed error_type=%s", type(error).__name__)


def main() -> None:
    settings = load_document_settings()
    configure_logging("INFO")
    service = build_service(settings)
    if not isinstance(service.queue, SqsQueue):
        raise RuntimeError("WORKER_SQS_COMPOSITION_REQUIRED")
    sqs = service.queue.client
    stop = threading.Event()

    def shutdown(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    next_sweep = 0.0
    futures: set[Future[None]] = set()
    with ThreadPoolExecutor(max_workers=settings.job_workers) as pool:
        while not stop.is_set():
            try:
                if time.monotonic() >= next_sweep:
                    service.dispatch_due()
                    next_sweep = time.monotonic() + settings.poll_seconds
                futures = {f for f in futures if not f.done()}
                free = settings.job_workers - len(futures)
                if free <= 0:
                    stop.wait(0.25)
                    continue
                response = sqs.receive_message(
                    QueueUrl=settings.queue_url,
                    MaxNumberOfMessages=free,
                    WaitTimeSeconds=10,
                    VisibilityTimeout=300,
                )
                for message in response.get("Messages", []):
                    futures.add(pool.submit(handle_message, service, sqs, settings, dict(message)))
            except (AwsError, BotoCoreError, ClientError):
                logger.warning("worker_transport_retry")
                stop.wait(5)


if __name__ == "__main__":
    main()

"""Explicit synchronous SDK adapter for asynchronous document-level Textract jobs.

Dynamic dictionaries/Any are confined to this AWS SDK/JSON boundary.
"""

import base64
import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any, Literal
from uuid import uuid4

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import Field

from app.document_conversion.contracts import Model, Source
from app.document_conversion.provider import Analysis, parse_analysis


class AwsError(RuntimeError):
    def __init__(self, code: str, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def translate_error(error: BotoCoreError | ClientError) -> AwsError:
    if isinstance(error, ClientError):
        code = str(error.response.get("Error", {}).get("Code", "AWS_ERROR"))
        retryable = code in {
            "ThrottlingException",
            "ProvisionedThroughputExceededException",
            "LimitExceededException",
            "InternalServerError",
            "InternalServerException",
            "ServiceUnavailable",
            "SlowDown",
            "RequestTimeout",
            "RequestTimeoutException",
            "Throttling",
            "TooManyRequestsException",
        }
        # Only service error codes, never StatusMessage/document payloads.
        return AwsError(code if code.isalnum() else "AWS_ERROR", retryable)
    return AwsError("AWS_TRANSPORT_ERROR", retryable=True)


def sdk_config(io_concurrency: int = 4) -> Config:
    return Config(
        connect_timeout=5,
        read_timeout=30,
        retries={"mode": "standard", "total_max_attempts": 3},
        max_pool_connections=io_concurrency,
        signature_version="v4",
    )


class BoundedSdkClient:
    """Share a real in-flight-call limit across SDK clients at composition time."""

    def __init__(self, client: Any, gate: BoundedSemaphore) -> None:
        self.client = client
        self.gate = gate

    def __getattr__(self, name: str) -> Callable[..., Any]:
        operation = getattr(self.client, name)

        def limited(*args: Any, **kwargs: Any) -> Any:
            with self.gate:
                return operation(*args, **kwargs)

        return limited


class S3Source(Model):
    bucket: str = Field(min_length=3)
    key: str = Field(min_length=1)
    region: str = Field(min_length=1)
    version: str | None = None
    checksum_sha256: str | None = None
    etag: str | None = None

    def document_source(self) -> Source:
        return Source(
            identity=f"s3://{self.bucket}/{self.key}",
            bucket=self.bucket,
            key=self.key,
            version=self.version,
            checksum_sha256=self.checksum_sha256,
            etag=self.etag,
        )


class JobHandle(Model):
    job_id: str
    submitted_at: int = 0
    source: S3Source
    request_token: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9-_]+$")


class JobCheck(Model):
    status: Literal["IN_PROGRESS", "SUCCEEDED", "PARTIAL_SUCCESS", "FAILED"]
    pages: int | None = None


class WaitTimeout(TimeoutError):
    def __init__(self, handle: JobHandle) -> None:
        super().__init__("TEXTRACT_WAIT_TIMEOUT_RESUME_WITH_HANDLE")
        self.handle = handle


class Collected(Model):
    # Raw response belongs here once, not in every normalized page.
    raw: dict[str, Any]


class TextractAdapter:
    def __init__(
        self,
        client: Any,
        region: str,
        max_blocks: int = 100_000,
        max_json_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.client = client
        self.region = region
        self.max_blocks = max_blocks
        self.max_json_bytes = max_json_bytes

    def submit(self, source: S3Source, request_token: str) -> JobHandle:
        if source.region != self.region:
            raise AwsError("REGION_MISMATCH")
        # Validate BEFORE submitting (including caller-controlled token length/characters).
        validated = JobHandle(
            job_id="pending",
            submitted_at=int(time.time()),
            source=source,
            request_token=request_token,
        )
        location = {"Bucket": source.bucket, "Name": source.key}
        if source.version:
            location["Version"] = source.version
        try:
            result = self.client.start_document_analysis(
                DocumentLocation={"S3Object": location},
                FeatureTypes=["TABLES", "LAYOUT"],
                ClientRequestToken=validated.request_token,
            )
        except (BotoCoreError, ClientError) as error:
            raise translate_error(error) from None
        return validated.model_copy(update={"job_id": str(result["JobId"])})

    def _get(self, handle: JobHandle, token: str | None = None) -> dict[str, Any]:
        if handle.source.region != self.region:
            raise AwsError("REGION_MISMATCH")
        params: dict[str, Any] = {"JobId": handle.job_id, "MaxResults": 1000}
        if token:
            params["NextToken"] = token
        try:
            result = dict(self.client.get_document_analysis(**params))
            if "JobStatus" not in result:
                raise AwsError("INVALID_TEXTRACT_STATUS_RESPONSE")
            return result
        except (BotoCoreError, ClientError) as error:
            raise translate_error(error) from None

    def check(self, handle: JobHandle) -> JobCheck:
        analysis = parse_analysis(self._get(handle))
        return JobCheck(status=analysis.status, pages=analysis.metadata.pages)

    def collect(self, handle: JobHandle, heartbeat: Callable[[], None] | None = None) -> Collected:
        result: dict[str, Any] = {}
        blocks: list[Any] = []
        warnings: list[Any] = []
        token: str | None = None
        seen: set[str] = set()
        total_bytes = 0
        status: str | None = None
        while True:
            if heartbeat:
                heartbeat()
            batch = self._get(handle, token)
            analysis: Analysis = parse_analysis(batch)
            if analysis.status in {"IN_PROGRESS", "FAILED"}:
                raise AwsError("TEXTRACT_" + analysis.status, analysis.status == "IN_PROGRESS")
            if status and status != analysis.status:
                raise AwsError("INCONSISTENT_PAGINATION_STATUS")
            status = analysis.status
            total_bytes += len(json.dumps(batch, ensure_ascii=False).encode("utf-8"))
            blocks.extend(batch.get("Blocks", []))
            warnings.extend(batch.get("Warnings", []))
            if len(blocks) > self.max_blocks or total_bytes > self.max_json_bytes:
                raise AwsError("COLLECTION_SIZE_LIMIT")
            if not result:
                result = {
                    k: v
                    for k, v in batch.items()
                    if k not in {"Blocks", "NextToken", "Warnings", "ResponseMetadata"}
                }
            token = analysis.next_token
            if not token:
                break
            if token in seen:
                raise AwsError("PAGINATION_TOKEN_CYCLE")
            seen.add(token)
        result["Blocks"] = blocks
        result["Warnings"] = warnings
        return Collected(raw=result)

    def wait_collect(
        self,
        handle: JobHandle,
        timeout_seconds: float = 300,
        interval_seconds: float = 5,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Collected:
        if timeout_seconds <= 0 or interval_seconds <= 0:
            raise ValueError("POSITIVE_WAIT_LIMITS_REQUIRED")
        deadline = clock() + timeout_seconds
        while clock() < deadline:
            check = self.check(handle)
            if check.status == "FAILED":
                raise AwsError("TEXTRACT_FAILED")
            if check.status != "IN_PROGRESS":
                return self.collect(handle)
            sleep(min(interval_seconds, max(0, deadline - clock())))
        raise WaitTimeout(handle)


def stage_pdf(
    client: Any,
    path: Path,
    bucket: str,
    prefix: str,
    region: str,
    encryption: Literal["AES256", "aws:kms"] = "AES256",
    kms_key_id: str | None = None,
    max_bytes: int = 25 * 1024 * 1024,
) -> S3Source:
    """Stream local PDF to a unique key; never deletes source files or S3 objects."""
    if encryption == "aws:kms" and not kms_key_id:
        raise ValueError("KMS_KEY_ID_REQUIRED")
    if not prefix.strip("/") or ".." in prefix.split("/"):
        raise ValueError("TRUSTED_NONEMPTY_PREFIX_REQUIRED")
    key = f"{prefix.strip('/')}/{uuid4().hex}/source.pdf"
    extra: dict[str, Any] = {"ContentType": "application/pdf", "ServerSideEncryption": encryption}
    if kms_key_id:
        extra["SSEKMSKeyId"] = kms_key_id
    with path.open("rb") as stream:
        if not stream.read(5).startswith(b"%PDF-"):
            raise ValueError("INVALID_PDF_SIGNATURE")
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        size = stream.tell()
        if size <= 0 or size > max_bytes:
            raise ValueError("PDF_SIZE_LIMIT")
        stream.seek(0)
        extra["ChecksumSHA256"] = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
        # A single streaming PutObject has an exact VersionId response and bounded memory.
        try:
            response = client.put_object(
                Bucket=bucket, Key=key, Body=stream, ContentLength=size, **extra
            )
        except (BotoCoreError, ClientError) as error:
            raise translate_error(error) from None
    return S3Source(
        bucket=bucket,
        key=key,
        region=region,
        version=response.get("VersionId"),
        checksum_sha256=digest,
        etag=response.get("ETag"),
    )

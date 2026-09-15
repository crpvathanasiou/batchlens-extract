"""Official SDK Stubber validation; no credentials/network or real sleeps."""

from io import BytesIO
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from app.document_conversion import convert_textract
from app.document_conversion.aws import (
    AwsError,
    JobHandle,
    S3Source,
    TextractAdapter,
    WaitTimeout,
    stage_pdf,
)
from app.document_jobs.storage import S3ObjectStore
from tests.document_conversion.fixtures import block
from tests.document_conversion.job_fakes import settings


def sdk(service: str) -> Any:
    session: Any = boto3.Session(
        region_name="eu-west-1", aws_access_key_id="testing", aws_secret_access_key="testing"
    )
    return session.client(service)


def handle() -> JobHandle:
    return JobHandle(
        job_id="provider-job",
        request_token="request-token",
        source=S3Source(bucket="test-bucket", key="input/a.pdf", region="eu-west-1", version="v1"),
    )


def test_submit_and_pagination_boundary_relationship_partial_success() -> None:
    client = sdk("textract")
    stub = Stubber(client)
    source = handle().source
    stub.add_response(
        "start_document_analysis",
        {"JobId": "provider-job"},
        {
            "DocumentLocation": {
                "S3Object": {"Bucket": source.bucket, "Name": source.key, "Version": "v1"}
            },
            "FeatureTypes": ["TABLES", "LAYOUT"],
            "ClientRequestToken": "request-token",
        },
    )
    stub.add_response(
        "get_document_analysis",
        {
            "JobStatus": "PARTIAL_SUCCESS",
            "DocumentMetadata": {"Pages": 1},
            "Blocks": [block("LAYOUT_TEXT", "layout", ("word",))],
            "NextToken": "next",
            "Warnings": [{"ErrorCode": "PAGE_ERROR", "Pages": [1]}],
        },
        {"JobId": "provider-job", "MaxResults": 1000},
    )
    stub.add_response(
        "get_document_analysis",
        {
            "JobStatus": "PARTIAL_SUCCESS",
            "DocumentMetadata": {"Pages": 1},
            "Blocks": [block("WORD", "word", Text="42.00 mg")],
        },
        {"JobId": "provider-job", "MaxResults": 1000, "NextToken": "next"},
    )
    with stub:
        adapter = TextractAdapter(client, "eu-west-1")
        result = adapter.collect(adapter.submit(source, "request-token"))
        doc = convert_textract(result.raw, source.document_source())
        assert doc.status == "PARTIAL_SUCCESS" and doc.pages[0].elements[0].text == "42.00 mg"
        assert any(w.code == "AWS_PAGE_ERROR" for w in doc.warnings)
        assert "NextToken" not in result.raw
    stub.assert_no_pending_responses()


def test_bounded_wait_returns_handle_without_resubmitting() -> None:
    client = sdk("textract")
    stub = Stubber(client)
    for _ in range(2):
        stub.add_response(
            "get_document_analysis",
            {"JobStatus": "IN_PROGRESS"},
            {"JobId": "provider-job", "MaxResults": 1000},
        )
    now = [0.0]

    def advance(seconds: float) -> None:
        now[0] += seconds

    with stub, pytest.raises(WaitTimeout) as caught:
        TextractAdapter(client, "eu-west-1").wait_collect(
            handle(), 2, 1, clock=lambda: now[0], sleep=advance
        )
    assert caught.value.handle == handle()
    stub.assert_no_pending_responses()


@pytest.mark.parametrize("state", ["FAILED", "IN_PROGRESS"])
def test_collect_does_not_return_empty_success(state: str) -> None:
    client = sdk("textract")
    stub = Stubber(client)
    stub.add_response("get_document_analysis", {"JobStatus": state})
    with stub, pytest.raises(AwsError, match="TEXTRACT_" + state):
        TextractAdapter(client, "eu-west-1").collect(handle())


def test_throttling_http_400_is_retryable_and_payload_is_not_exposed() -> None:
    client = sdk("textract")
    stub = Stubber(client)
    stub.add_client_error(
        "get_document_analysis",
        "ProvisionedThroughputExceededException",
        "sensitive provider payload",
        400,
    )
    with stub, pytest.raises(AwsError) as caught:
        TextractAdapter(client, "eu-west-1").check(handle())
    assert caught.value.retryable and "sensitive" not in str(caught.value)


def test_local_pdf_stages_stream_then_same_submit_path(tmp_path: Path) -> None:
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF")
    s3 = sdk("s3")
    stub = Stubber(s3)
    stub.add_response(
        "put_object",
        {"VersionId": "version", "ETag": "etag"},
        {
            "Bucket": "test-bucket",
            "Key": ANY,
            "Body": ANY,
            "ContentLength": path.stat().st_size,
            "ChecksumSHA256": ANY,
            "ContentType": "application/pdf",
            "ServerSideEncryption": "AES256",
        },
    )
    with stub:
        source = stage_pdf(s3, path, "test-bucket", "trusted", "eu-west-1")
    assert source.version == "version" and source.checksum_sha256
    assert source.key.startswith("trusted/") and path.exists()
    tx = sdk("textract")
    st = Stubber(tx)
    st.add_response(
        "start_document_analysis",
        {"JobId": "job"},
        {
            "DocumentLocation": {
                "S3Object": {"Bucket": source.bucket, "Name": source.key, "Version": "version"}
            },
            "FeatureTypes": ["TABLES", "LAYOUT"],
            "ClientRequestToken": "retry-token",
        },
    )
    with st:
        assert TextractAdapter(tx, "eu-west-1").submit(source, "retry-token").source == source


def test_s3_start_pins_head_version_for_signature_read() -> None:
    from tests.document_conversion.job_fakes import make_service

    service, _, _, _ = make_service()
    grant = service.initiate("alice", "record.pdf", 9)
    job = service.owned(grant.job_id, "alice")
    client = sdk("s3")
    stub = Stubber(client)
    stub.add_response(
        "head_object",
        {
            "VersionId": "immutable-v1",
            "ContentLength": 9,
            "ContentType": "application/pdf",
            "ServerSideEncryption": "AES256",
            "Metadata": {"job-id": job.id},
        },
        {"Bucket": job.source.bucket, "Key": job.source.key},
    )
    stub.add_response(
        "get_object",
        {"Body": StreamingBody(BytesIO(b"%PDF-"), 5)},
        {
            "Bucket": job.source.bucket,
            "Key": job.source.key,
            "VersionId": "immutable-v1",
            "Range": "bytes=0-4",
        },
    )
    with stub:
        assert S3ObjectStore(client, settings()).verify(job).version == "immutable-v1"


def test_sdk_semaphore_bounds_actual_simultaneous_invocations() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, BoundedSemaphore, Lock

    from app.document_conversion.aws import BoundedSdkClient

    barrier = Barrier(2)
    lock = Lock()
    counts = [0, 0]

    class Client:
        def operation(self, value: int) -> int:
            with lock:
                counts[0] += 1
                counts[1] = max(counts)
            barrier.wait(timeout=2)
            with lock:
                counts[0] -= 1
            return value * 2

    bounded = BoundedSdkClient(Client(), BoundedSemaphore(2))
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(bounded.operation, i) for i in range(6)]
        assert [f.result() for f in futures] == [0, 2, 4, 6, 8, 10]
    assert counts[1] == 2

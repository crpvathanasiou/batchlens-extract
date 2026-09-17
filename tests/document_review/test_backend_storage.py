"""AWS boundary tests for the small head CAS and exact source version stream."""

from io import BytesIO
from typing import Any, cast

import boto3
from botocore.response import StreamingBody
from botocore.stub import Stubber
from mypy_boto3_dynamodb import DynamoDBClient
from mypy_boto3_s3 import S3Client

from app.document_conversion.aws import S3Source
from app.document_jobs.contracts import Artifact
from app.document_jobs.settings import DocumentSettings
from app.document_review.contracts import ReviewHead
from app.document_review.storage import DynamoReviewStore, S3ObjectStore

REVISION_ID = "00000000-0000-4000-8000-000000000001"
NEXT_ID = "00000000-0000-4000-8000-000000000002"
BASELINE = Artifact(key="base.json", version="base-v1", content_type="application/json")
RAW = Artifact(key="raw.json", version="raw-v1", content_type="application/json")
REVISION = Artifact(key="review.json", version="review-v1", content_type="application/json")
SOURCE = S3Source(
    bucket="records-bucket",
    key="incoming/job/source.pdf",
    region="eu-west-1",
    version="pdf-version",
)


def settings() -> DocumentSettings:
    return DocumentSettings(
        region="eu-west-1",
        bucket="records-bucket",
        table="documents",
        queue_url="https://sqs.invalid/q",
        dlq_url="https://sqs.invalid/dlq",
        cognito_pool_id="pool",
        cognito_client_id="client",
        origin="https://example.invalid",
    )


def dynamo_client() -> DynamoDBClient:
    session: Any = boto3.Session()
    return cast(
        DynamoDBClient,
        session.client(
            "dynamodb",
            region_name="eu-west-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        ),
    )


def s3_client() -> S3Client:
    session: Any = boto3.Session()
    return cast(
        S3Client,
        session.client(
            "s3",
            region_name="eu-west-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        ),
    )


def head(revision_id: str = REVISION_ID, generation: int = 1) -> ReviewHead:
    return ReviewHead(
        job_id="job",
        owner="alice",
        generation=generation,
        revision_id=revision_id,
        revision=REVISION,
        baseline=BASELINE,
        accepted_source=SOURCE,
        raw=RAW,
        status="IN_REVIEW",
        expires_at=999,
    )


def test_dynamo_stubber_uses_small_head_and_exact_nullable_cas_shapes() -> None:
    dynamo = dynamo_client()
    store = DynamoReviewStore(dynamo, "documents")
    initial = head()
    expected_item = {
        "pk": {"S": "review#job"},
        "owner": {"S": "alice"},
        "generation": {"N": "1"},
        "revision_id": {"S": REVISION_ID},
        "revision": {"S": REVISION.model_dump_json()},
        "baseline": {"S": BASELINE.model_dump_json()},
        "accepted_source": {"S": SOURCE.model_dump_json()},
        "raw": {"S": RAW.model_dump_json()},
        "status": {"S": "IN_REVIEW"},
        "document_approval": {"NULL": True},
        "exports": {"NULL": True},
        "expires_at": {"N": "999"},
    }
    with Stubber(dynamo) as stubber:
        stubber.add_response(
            "put_item",
            {},
            {
                "TableName": "documents",
                "Item": expected_item,
                "ConditionExpression": "attribute_not_exists(pk)",
            },
        )
        assert store.publish(initial, None)

    updated = head(NEXT_ID, 2)
    with Stubber(dynamo) as stubber:
        stubber.add_client_error(
            "update_item",
            service_error_code="ConditionalCheckFailedException",
            expected_params={
                "TableName": "documents",
                "Key": {"pk": {"S": "review#job"}},
                "UpdateExpression": (
                    "SET generation = :generation, revision_id = :revision_id, "
                    "revision = :revision, #status = :status, "
                    "document_approval = :approval, exports = :exports, expires_at = :expires"
                ),
                "ConditionExpression": (
                    "#owner = :owner AND revision_id = :expected "
                    "AND generation = :previous_generation"
                ),
                "ExpressionAttributeNames": {"#owner": "owner", "#status": "status"},
                "ExpressionAttributeValues": {
                    ":owner": {"S": "alice"},
                    ":expected": {"S": REVISION_ID},
                    ":previous_generation": {"N": "1"},
                    ":generation": {"N": "2"},
                    ":revision_id": {"S": NEXT_ID},
                    ":revision": {"S": REVISION.model_dump_json()},
                    ":status": {"S": "IN_REVIEW"},
                    ":approval": {"NULL": True},
                    ":exports": {"NULL": True},
                    ":expires": {"N": "999"},
                },
            },
        )
        assert not store.publish(updated, REVISION_ID)


def test_dynamo_get_reconstructs_head_without_revision_payload() -> None:
    dynamo = dynamo_client()
    store = DynamoReviewStore(dynamo, "documents")
    item = {
        "pk": {"S": "review#job"},
        "owner": {"S": "alice"},
        "generation": {"N": "1"},
        "revision_id": {"S": REVISION_ID},
        "revision": {"S": REVISION.model_dump_json()},
        "baseline": {"S": BASELINE.model_dump_json()},
        "accepted_source": {"S": SOURCE.model_dump_json()},
        "raw": {"S": RAW.model_dump_json()},
        "status": {"S": "IN_REVIEW"},
        "document_approval": {"NULL": True},
        "exports": {"NULL": True},
        "expires_at": {"N": "999"},
    }
    with Stubber(dynamo) as stubber:
        stubber.add_response(
            "get_item",
            {"Item": item},
            {
                "TableName": "documents",
                "Key": {"pk": {"S": "review#job"}},
                "ConsistentRead": True,
            },
        )
        assert store.get("job") == head()
        assert "payload" not in item


def test_s3_source_stream_pins_version_and_closes_body() -> None:
    s3 = s3_client()
    store = S3ObjectStore(s3, settings())
    raw = BytesIO(b"%PDF-exact")
    body = StreamingBody(raw, len(b"%PDF-exact"))
    with Stubber(s3) as stubber:
        stubber.add_response(
            "get_object",
            {"Body": body, "ContentLength": len(b"%PDF-exact")},
            {
                "Bucket": SOURCE.bucket,
                "Key": SOURCE.key,
                "VersionId": SOURCE.version,
            },
        )
        assert b"".join(store.stream_source(SOURCE)) == b"%PDF-exact"
    assert raw.closed


def test_revision_and_exports_use_uuid_namespace() -> None:
    s3 = s3_client()
    store = S3ObjectStore(s3, settings())
    prefix = f"documents/results/job/review/revisions/{REVISION_ID}"
    with Stubber(s3) as stubber:
        stubber.add_response(
            "put_object",
            {"VersionId": "v1"},
            {
                "Bucket": "records-bucket",
                "Key": f"{prefix}/review.json",
                "Body": b"{}",
                "ContentType": "application/json",
                "ServerSideEncryption": "AES256",
                "IfNoneMatch": "*",
            },
        )
        artifact = store.put_revision("job", REVISION_ID, b"{}")
    assert artifact.key.endswith(f"{REVISION_ID}/review.json")

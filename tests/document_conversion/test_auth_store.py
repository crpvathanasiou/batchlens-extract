"""Cryptographic authentication and actual DynamoDB request/condition validation."""

import json
import time
from typing import Any

import jwt
import pytest
from botocore.stub import ANY, Stubber
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.document_jobs.auth import CognitoAuth
from app.document_jobs.contracts import JobError
from app.document_jobs.storage import DynamoJobStore
from tests.document_conversion.job_fakes import make_service
from tests.document_conversion.test_aws import sdk


@pytest.mark.parametrize("change", [None, "expired", "issuer", "client", "id_token", "unsigned"])
def test_cognito_signature_issuer_expiry_token_use_and_client(
    change: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    auth = CognitoAuth("eu-west-1", "pool", "client")
    public = jwt.PyJWK.from_json(RSAAlgorithm.to_jwk(private.public_key()))

    def key(token: str) -> jwt.PyJWK:
        return public

    monkeypatch.setattr(auth.keys, "get_signing_key_from_jwt", key)
    claims: dict[str, Any] = {
        "sub": "owner-123",
        "iss": auth.issuer,
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "token_use": "access",
        "client_id": "client",
    }
    if change == "expired":
        claims["exp"] = int(time.time()) - 5
    if change == "issuer":
        claims["iss"] = "https://attacker.invalid"
    if change == "client":
        claims["client_id"] = "other-client"
    if change == "id_token":
        claims["token_use"] = "id"
    token = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "key"})
    if change == "unsigned":
        token = jwt.encode(claims, key="", algorithm="none")
    if change is None:
        assert auth.verify(token) == "owner-123"
    else:
        with pytest.raises(JobError, match="UNAUTHORIZED"):
            auth.verify(token)


def test_dynamo_reloaded_job_and_stale_revision_cannot_overwrite() -> None:
    service, _, _, _ = make_service()
    job_id = service.initiate("alice", "a.pdf", 9).job_id
    job = service.owned(job_id, "alice")
    client = sdk("dynamodb")
    stub = Stubber(client)
    stub.add_response(
        "get_item",
        {"Item": {"pk": {"S": "job#" + job_id}, "payload": {"S": job.model_dump_json()}}},
        {"TableName": "jobs", "Key": {"pk": {"S": "job#" + job_id}}, "ConsistentRead": True},
    )
    stub.add_client_error(
        "update_item",
        "ConditionalCheckFailedException",
        "stale",
        400,
        expected_params={
            "TableName": "jobs",
            "Key": {"pk": {"S": "job#" + job_id}},
            "UpdateExpression": "SET payload = :p, revision = :nr, due = :d, phase = :s",
            "ConditionExpression": "revision = :r AND lease_token = :l",
            "ExpressionAttributeValues": {
                ":r": {"N": "0"},
                ":nr": {"N": "1"},
                ":p": ANY,
                ":d": {"N": "0"},
                ":s": {"S": "QUEUED"},
                ":l": {"S": "lost-lease"},
            },
        },
    )
    with stub:
        store = DynamoJobStore(client, "jobs")
        restored = store.get(job_id)
        assert restored is not None and restored == job and restored.owner == "alice"
        assert not store.replace(
            job.model_copy(update={"revision": 1, "phase": "QUEUED"}), 0, "lost-lease"
        )
    stub.assert_no_pending_responses()


def test_download_grant_is_pinned_and_attachment_only() -> None:
    from app.document_jobs.contracts import Artifact
    from app.document_jobs.storage import S3ObjectStore
    from tests.document_conversion.job_fakes import settings

    client = sdk("s3")
    url = S3ObjectStore(client, settings()).download(
        Artifact(
            key="documents/results/job/document.html",
            version="fixed-version",
            content_type="text/html",
        ),
        "document.html",
    )
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(url).query)
    assert query["versionId"] == ["fixed-version"]
    assert query["response-content-disposition"] == ['attachment; filename="document.html"']
    assert "signature" in json.dumps(query).lower()


def test_owner_scan_aliases_reserved_word_and_follows_pagination() -> None:
    service, _, _, _ = make_service()
    job_id = service.initiate("alice", "a.pdf", 9).job_id
    job = service.owned(job_id, "alice")
    client = sdk("dynamodb")
    stub = Stubber(client)
    expected = {
        "TableName": "jobs",
        "FilterExpression": "begins_with(pk, :p) AND #owner = :o",
        "ExpressionAttributeValues": {":p": {"S": "job#"}, ":o": {"S": "alice"}},
        "ExpressionAttributeNames": {"#owner": "owner"},
        "ConsistentRead": True,
    }
    stub.add_response(
        "scan", {"Items": [], "LastEvaluatedKey": {"pk": {"S": "job#cursor"}}}, expected
    )
    stub.add_response(
        "scan",
        {"Items": [{"payload": {"S": job.model_dump_json()}}]},
        {**expected, "ExclusiveStartKey": {"pk": {"S": "job#cursor"}}},
    )
    with stub:
        assert list(DynamoJobStore(client, "jobs").owned("alice")) == [job]

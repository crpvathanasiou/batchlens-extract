"""DynamoDB CAS/leases, S3 versioned artifacts, and SQS. Dynamic SDK boundary only."""

import json
import time
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError

from app.document_conversion.aws import S3Source, translate_error
from app.document_jobs.contracts import ACTIVE, Artifact, Job, JobError, UploadGrant
from app.document_jobs.settings import DocumentSettings


def conditional_failed(error: ClientError) -> bool:
    return error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


class DynamoJobStore:
    def __init__(self, client: Any, table: str) -> None:
        self.client = client
        self.table = table

    def _call(self, operation: str, **kwargs: Any) -> Any:
        try:
            return getattr(self.client, operation)(TableName=self.table, **kwargs)
        except ClientError as error:
            if conditional_failed(error):
                return None
            raise translate_error(error) from None
        except BotoCoreError as error:
            raise translate_error(error) from None

    def create(self, job: Job) -> None:
        result = self._call(
            "put_item", Item=self._item(job), ConditionExpression="attribute_not_exists(pk)"
        )
        if result is None:
            raise JobError("JOB_ALREADY_EXISTS")

    def _item(self, job: Job) -> dict[str, Any]:
        return {
            "pk": {"S": "job#" + job.id},
            "payload": {"S": job.model_dump_json()},
            "revision": {"N": str(job.revision)},
            "due": {"N": str(job.next_due)},
            "owner": {"S": job.owner},
            "phase": {"S": job.phase},
            "expires_at": {"N": str(job.expires_at)},
        }

    def get(self, job_id: str) -> Job | None:
        response = self._call("get_item", Key={"pk": {"S": "job#" + job_id}}, ConsistentRead=True)
        item = response.get("Item")
        return Job.model_validate_json(item["payload"]["S"]) if item else None

    def replace(self, job: Job, previous_revision: int, lease: str | None = None) -> bool:
        values = {
            ":r": {"N": str(previous_revision)},
            ":nr": {"N": str(job.revision)},
            ":p": {"S": job.model_dump_json()},
            ":d": {"N": str(job.next_due)},
            ":s": {"S": job.phase},
        }
        condition = "revision = :r"
        if lease:
            condition += " AND lease_token = :l"
            values[":l"] = {"S": lease}
        else:
            condition += " AND (attribute_not_exists(lease_until) OR lease_until < :now)"
            values[":now"] = {"N": str(int(time.time()))}
        return (
            self._call(
                "update_item",
                Key={"pk": {"S": "job#" + job.id}},
                UpdateExpression="SET payload = :p, revision = :nr, due = :d, phase = :s",
                ConditionExpression=condition,
                ExpressionAttributeValues=values,
            )
            is not None
        )

    def _scan(self, expression: str, values: dict[str, Any]) -> Iterator[Job]:
        cursor: dict[str, Any] | None = None
        while True:
            args: dict[str, Any] = {
                "FilterExpression": expression,
                "ExpressionAttributeValues": values,
                "ConsistentRead": True,
            }
            if "#owner" in expression:
                args["ExpressionAttributeNames"] = {"#owner": "owner"}
            if cursor:
                args["ExclusiveStartKey"] = cursor
            result = self._call("scan", **args)
            for item in result.get("Items", []):
                yield Job.model_validate_json(item["payload"]["S"])
            cursor = result.get("LastEvaluatedKey")
            if not cursor:
                break

    def due(self, now: int) -> Iterator[Job]:
        for job in self._scan(
            "begins_with(pk, :p) AND due <= :n", {":p": {"S": "job#"}, ":n": {"N": str(now)}}
        ):
            if job.phase in ACTIVE:
                yield job

    def settled(self) -> Iterator[Job]:
        for job in self._scan("begins_with(pk, :p)", {":p": {"S": "job#"}}):
            if job.phase in {"FAILED", "SUCCEEDED", "PARTIAL_SUCCESS"}:
                yield job

    def owned(self, owner: str) -> Iterator[Job]:
        yield from self._scan(
            "begins_with(pk, :p) AND #owner = :o", {":p": {"S": "job#"}, ":o": {"S": owner}}
        )

    def claim(self, job: Job, now: int, lease_seconds: int) -> str | None:
        token = uuid4().hex
        result = self._call(
            "update_item",
            Key={"pk": {"S": "job#" + job.id}},
            UpdateExpression="SET lease_token = :l, lease_until = :u",
            ConditionExpression="revision = :r AND (attribute_not_exists(lease_until) "
            "OR lease_until < :n)",
            ExpressionAttributeValues={
                ":l": {"S": token},
                ":u": {"N": str(now + lease_seconds)},
                ":n": {"N": str(now)},
                ":r": {"N": str(job.revision)},
            },
        )
        return token if result is not None else None

    def heartbeat(self, job_id: str, lease: str, until: int) -> bool:
        return (
            self._call(
                "update_item",
                Key={"pk": {"S": "job#" + job_id}},
                UpdateExpression="SET lease_until = :u",
                ConditionExpression="lease_token = :l",
                ExpressionAttributeValues={":u": {"N": str(until)}, ":l": {"S": lease}},
            )
            is not None
        )

    def release(self, job_id: str, lease: str) -> None:
        self._call(
            "update_item",
            Key={"pk": {"S": "job#" + job_id}},
            UpdateExpression="REMOVE lease_token, lease_until",
            ConditionExpression="lease_token = :l",
            ExpressionAttributeValues={":l": {"S": lease}},
        )

    def acquire_slot(self, job_id: str, limit: int) -> tuple[int, str] | None:
        # Search ALL existing owners before choosing an empty slot: restart after acquire
        # but before persisting Job.slot must not allocate a second slot for the same job.
        # Rotate generation on reclaim so a stale FAILED cleanup cannot drop the new hold.
        for slot in range(limit):
            result = self._call("get_item", Key={"pk": {"S": f"slot#{slot}"}}, ConsistentRead=True)
            item = result.get("Item", {})
            if item.get("job_id", {}).get("S") == job_id:
                generation = uuid4().hex
                if (
                    self._call(
                        "update_item",
                        Key={"pk": {"S": f"slot#{slot}"}},
                        UpdateExpression="SET generation = :g",
                        ConditionExpression="job_id = :j",
                        ExpressionAttributeValues={":g": {"S": generation}, ":j": {"S": job_id}},
                    )
                    is not None
                ):
                    return slot, generation
        generation = uuid4().hex
        for slot in range(limit):
            if (
                self._call(
                    "put_item",
                    Item={
                        "pk": {"S": f"slot#{slot}"},
                        "job_id": {"S": job_id},
                        "generation": {"S": generation},
                    },
                    ConditionExpression="attribute_not_exists(pk)",
                )
                is not None
            ):
                return slot, generation
        return None

    def release_slot(self, job_id: str, slot: int, generation: str) -> None:
        # Generation must match: a stale FAILED snapshot must not drop a reacquired slot.
        self._call(
            "delete_item",
            Key={"pk": {"S": f"slot#{slot}"}},
            ConditionExpression="job_id = :j AND generation = :g",
            ExpressionAttributeValues={":j": {"S": job_id}, ":g": {"S": generation}},
        )


class S3ObjectStore:
    def __init__(self, client: Any, settings: DocumentSettings) -> None:
        self.client = client
        self.settings = settings

    def grant(self, job: Job) -> UploadGrant:
        fields = {
            "Content-Type": "application/pdf",
            "x-amz-server-side-encryption": "AES256",
            "x-amz-meta-job-id": job.id,
        }
        result = self.client.generate_presigned_post(
            Bucket=self.settings.bucket,
            Key=job.source.key,
            Fields=fields,
            Conditions=[
                {"Content-Type": "application/pdf"},
                {"x-amz-server-side-encryption": "AES256"},
                {"x-amz-meta-job-id": job.id},
                ["content-length-range", job.expected_bytes, job.expected_bytes],
            ],
            ExpiresIn=self.settings.upload_seconds,
        )
        return UploadGrant(
            job_id=job.id,
            url=result["url"],
            fields=result["fields"],
            expires_in=self.settings.upload_seconds,
        )

    def verify(self, job: Job) -> S3Source:
        try:
            head = self.client.head_object(Bucket=job.source.bucket, Key=job.source.key)
            version = head.get("VersionId")
            if not version or version == "null":
                raise JobError("SOURCE_VERSIONING_REQUIRED")
            if head["ContentLength"] != job.expected_bytes or (
                head.get("Metadata", {}).get("job-id") != job.id
                or head.get("ContentType") != "application/pdf"
                or head.get("ServerSideEncryption") != "AES256"
            ):
                raise JobError("UPLOAD_METADATA_MISMATCH", 422)
            response = self.client.get_object(
                Bucket=job.source.bucket, Key=job.source.key, VersionId=version, Range="bytes=0-4"
            )
            body = response["Body"]
            try:
                if body.read(5) != b"%PDF-":
                    raise JobError("INVALID_PDF_SIGNATURE", 422)
            finally:
                body.close()
        except (BotoCoreError, ClientError) as error:
            raise translate_error(error) from None
        return job.source.model_copy(update={"version": version, "etag": head.get("ETag")})

    def put(self, job_id: str, name: str, body: bytes, content_type: str) -> Artifact:
        key = f"{self.settings.prefix}/results/{job_id}/{name}"
        try:
            result = self.client.put_object(
                Bucket=self.settings.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except (BotoCoreError, ClientError) as error:
            raise translate_error(error) from None
        version = result.get("VersionId")
        if not version or version == "null":
            raise JobError("ARTIFACT_VERSIONING_REQUIRED")
        return Artifact(key=key, version=version, content_type=content_type)

    def read(self, artifact: Artifact) -> bytes:
        try:
            response = self.client.get_object(
                Bucket=self.settings.bucket, Key=artifact.key, VersionId=artifact.version
            )
            body = response["Body"]
            try:
                if response["ContentLength"] > self.settings.max_json_bytes:
                    raise JobError("ARTIFACT_READ_SIZE_LIMIT")
                data: bytes = body.read(self.settings.max_json_bytes + 1)
                if len(data) > self.settings.max_json_bytes:
                    raise JobError("ARTIFACT_READ_SIZE_LIMIT")
                return data
            finally:
                body.close()
        except (BotoCoreError, ClientError) as error:
            raise translate_error(error) from None

    def download(self, artifact: Artifact, filename: str) -> str:
        return str(
            self.client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.settings.bucket,
                    "Key": artifact.key,
                    "VersionId": artifact.version,
                    "ResponseContentDisposition": f'attachment; filename="{filename}"',
                    "ResponseContentType": artifact.content_type,
                },
                ExpiresIn=60,
            )
        )


class SqsQueue:
    def __init__(self, client: Any, url: str, dlq_url: str) -> None:
        self.client = client
        self.url = url
        self.dlq_url = dlq_url

    def send(self, job_id: str) -> None:
        try:
            self.client.send_message(QueueUrl=self.url, MessageBody=json.dumps({"job_id": job_id}))
        except (BotoCoreError, ClientError) as error:
            raise translate_error(error) from None

    def dead_letter(self, job_id: str, code: str) -> None:
        try:
            self.client.send_message(
                QueueUrl=self.dlq_url, MessageBody=json.dumps({"job_id": job_id, "code": code})
            )
        except (BotoCoreError, ClientError) as error:
            raise translate_error(error) from None

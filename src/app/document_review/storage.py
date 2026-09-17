"""Small Dynamo review head and immutable versioned S3 objects."""

from collections.abc import Iterable, Iterator
from typing import Any, Literal

from botocore.exceptions import BotoCoreError, ClientError

from app.document_conversion.aws import S3Source, translate_error
from app.document_jobs.contracts import Artifact, JobError
from app.document_jobs.settings import DocumentSettings
from app.document_review.contracts import (
    DocumentApproval,
    ExportPointers,
    ReviewError,
    ReviewHead,
    RevisionId,
)


def _conditional_failed(error: ClientError) -> bool:
    return error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


class DynamoReviewStore:
    def __init__(self, client: Any, table: str) -> None:
        self.client = client
        self.table = table

    def _call(self, operation: str, **kwargs: Any) -> Any | None:
        try:
            return getattr(self.client, operation)(TableName=self.table, **kwargs)
        except ClientError as error:
            if _conditional_failed(error):
                return None
            raise translate_error(error) from None
        except BotoCoreError as error:
            raise translate_error(error) from None

    @staticmethod
    def _key(job_id: str) -> dict[str, dict[str, str]]:
        return {"pk": {"S": f"review#{job_id}"}}

    @staticmethod
    def _artifact(value: Artifact) -> dict[str, str]:
        return {"S": value.model_dump_json()}

    @staticmethod
    def _optional(value: object | None) -> dict[str, str] | dict[str, bool]:
        if value is None:
            return {"NULL": True}
        if isinstance(value, ExportPointers | DocumentApproval):
            return {"S": value.model_dump_json()}
        raise TypeError("unsupported head value")

    def get(self, job_id: str) -> ReviewHead | None:
        result = self._call("get_item", Key=self._key(job_id), ConsistentRead=True)
        item = result.get("Item") if result else None
        if not item:
            return None
        approval = item.get("document_approval", {})
        exports = item.get("exports", {})
        return ReviewHead(
            job_id=job_id,
            owner=item["owner"]["S"],
            generation=int(item["generation"]["N"]),
            revision_id=item["revision_id"]["S"],
            revision=Artifact.model_validate_json(item["revision"]["S"]),
            baseline=Artifact.model_validate_json(item["baseline"]["S"]),
            accepted_source=S3Source.model_validate_json(item["accepted_source"]["S"]),
            raw=Artifact.model_validate_json(item["raw"]["S"]),
            status=item["status"]["S"],
            document_approval=(
                DocumentApproval.model_validate_json(approval["S"]) if "S" in approval else None
            ),
            exports=ExportPointers.model_validate_json(exports["S"]) if "S" in exports else None,
            expires_at=int(item["expires_at"]["N"]),
        )

    def _item(self, head: ReviewHead) -> dict[str, object]:
        return {
            **self._key(head.job_id),
            "owner": {"S": head.owner},
            "generation": {"N": str(head.generation)},
            "revision_id": {"S": head.revision_id},
            "revision": self._artifact(head.revision),
            "baseline": self._artifact(head.baseline),
            "accepted_source": {"S": head.accepted_source.model_dump_json()},
            "raw": self._artifact(head.raw),
            "status": {"S": head.status},
            "document_approval": self._optional(head.document_approval),
            "exports": self._optional(head.exports),
            "expires_at": {"N": str(head.expires_at)},
        }

    def publish(self, head: ReviewHead, expected_revision: RevisionId | None) -> bool:
        if expected_revision is None:
            return (
                self._call(
                    "put_item",
                    Item=self._item(head),
                    ConditionExpression="attribute_not_exists(pk)",
                )
                is not None
            )
        values = {
            ":owner": {"S": head.owner},
            ":expected": {"S": expected_revision},
            ":previous_generation": {"N": str(head.generation - 1)},
            ":generation": {"N": str(head.generation)},
            ":revision_id": {"S": head.revision_id},
            ":revision": self._artifact(head.revision),
            ":status": {"S": head.status},
            ":approval": self._optional(head.document_approval),
            ":exports": self._optional(head.exports),
            ":expires": {"N": str(head.expires_at)},
        }
        return (
            self._call(
                "update_item",
                Key=self._key(head.job_id),
                UpdateExpression=(
                    "SET generation = :generation, revision_id = :revision_id, "
                    "revision = :revision, #status = :status, "
                    "document_approval = :approval, exports = :exports, expires_at = :expires"
                ),
                ConditionExpression=(
                    "#owner = :owner AND revision_id = :expected "
                    "AND generation = :previous_generation"
                ),
                ExpressionAttributeNames={"#owner": "owner", "#status": "status"},
                ExpressionAttributeValues=values,
            )
            is not None
        )


class S3ObjectStore:
    def __init__(self, client: Any, settings: DocumentSettings) -> None:
        self.client = client
        self.settings = settings

    def _put(self, key: str, body: bytes, content_type: str) -> Artifact:
        try:
            result = self.client.put_object(
                Bucket=self.settings.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                ServerSideEncryption="AES256",
                IfNoneMatch="*",
            )
        except (BotoCoreError, ClientError) as error:
            raise translate_error(error) from None
        version = result.get("VersionId")
        if not version or version == "null":
            raise JobError("ARTIFACT_VERSIONING_REQUIRED")
        return Artifact(key=key, version=version, content_type=content_type)

    def _namespace(self, job_id: str, revision_id: str) -> str:
        return f"{self.settings.prefix}/results/{job_id}/review/revisions/{revision_id}"

    def put_revision(self, job_id: str, revision_id: str, body: bytes) -> Artifact:
        return self._put(
            f"{self._namespace(job_id, revision_id)}/review.json",
            body,
            "application/json",
        )

    def put_export(
        self, job_id: str, revision_id: str, format: Literal["html", "json"], body: bytes
    ) -> Artifact:
        content_type = "text/html" if format == "html" else "application/json"
        return self._put(
            f"{self._namespace(job_id, revision_id)}/exports/document.{format}",
            body,
            content_type,
        )

    def read(self, artifact: Artifact) -> bytes:
        try:
            response = self.client.get_object(
                Bucket=self.settings.bucket, Key=artifact.key, VersionId=artifact.version
            )
            body = response["Body"]
            try:
                length = int(response.get("ContentLength", 0))
                if length > self.settings.max_json_bytes:
                    raise JobError("ARTIFACT_READ_SIZE_LIMIT")
                data: bytes = body.read(self.settings.max_json_bytes + 1)
                if len(data) > self.settings.max_json_bytes:
                    raise JobError("ARTIFACT_READ_SIZE_LIMIT")
                return data
            finally:
                body.close()
        except (BotoCoreError, ClientError) as error:
            raise translate_error(error) from None

    def stream_source(self, source: S3Source) -> Iterable[bytes]:
        if source.version is None:
            raise ReviewError("SOURCE_VERSION_REQUIRED", 409)

        def chunks() -> Iterator[bytes]:
            try:
                response = self.client.get_object(
                    Bucket=source.bucket, Key=source.key, VersionId=source.version
                )
                body = response["Body"]
                try:
                    while chunk := body.read(64 * 1024):
                        yield chunk
                finally:
                    body.close()
            except (BotoCoreError, ClientError) as error:
                raise translate_error(error) from None

        return chunks()

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

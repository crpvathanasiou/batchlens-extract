"""Persistent, AWS-free adapters for the local review acceptance harness.

``JOB_ID`` and ``OWNER`` are synthetic. Generated review state stays under the
data directory; supplied originals are read-only.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from threading import RLock
from typing import Literal, cast

from app.document_conversion.aws import S3Source
from app.document_conversion.contracts import Document
from app.document_jobs.contracts import Artifact, Job
from app.document_review.contracts import ReviewHead

JOB_ID = "local-fexofenadine"
OWNER = "local-test-reviewer"


class LocalHarnessError(RuntimeError):
    """A safe startup or persistent-state validation error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_data_dir(data_dir: Path, inputs: Mapping[str, Path]) -> None:
    resolved = data_dir.resolve()
    for name, supplied in inputs.items():
        source = supplied.resolve()
        parent = source.parent
        if resolved == source or _contains(resolved, source):
            raise LocalHarnessError(
                f"DATA_DIR_OVERLAPS_INPUT: {resolved} would contain {name}: {source}"
            )
        if resolved == parent or _contains(parent, resolved):
            raise LocalHarnessError(
                f"DATA_DIR_OVERLAPS_INPUT_DIRECTORY: {resolved} overlaps {name}: {parent}"
            )


def ensure_manifest(data_dir: Path, inputs: Mapping[str, Path]) -> dict[str, object]:
    """Create once, then require the exact same absolute inputs and bytes."""
    validate_data_dir(data_dir, inputs)
    manifest_path = data_dir / "manifest.json"
    expected: dict[str, object] = {
        "schema_version": 1,
        "identity": {"job_id": JOB_ID, "owner": OWNER},
        "inputs": {
            name: {"path": str(path.resolve()), "sha256": sha256_file(path)}
            for name, path in sorted(inputs.items())
        },
    }
    if manifest_path.exists():
        try:
            actual = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise LocalHarnessError(f"INVALID_LOCAL_MANIFEST: {manifest_path}") from error
        if actual != expected:
            raise LocalHarnessError(
                "LOCAL_MANIFEST_MISMATCH: inputs changed; use a different --data-dir"
            )
        return expected
    if data_dir.exists() and any(data_dir.iterdir()):
        raise LocalHarnessError(f"LOCAL_DATA_DIR_NOT_EMPTY: {data_dir}; use a different --data-dir")
    _atomic_json(manifest_path, expected)
    return expected


class LocalReviewStore:
    """All three review ports, backed only by immutable files and an atomic head."""

    def __init__(
        self,
        data_dir: Path,
        source_path: Path,
        document_path: Path,
        textract_path: Path,
        html_path: Path,
        *,
        initialize_manifest: bool = True,
    ) -> None:
        self.data_dir = data_dir.resolve()
        self.source_path = source_path.resolve()
        self.document_path = document_path.resolve()
        self.textract_path = textract_path.resolve()
        self.html_path = html_path.resolve()
        self.inputs = {
            "source": self.source_path,
            "document": self.document_path,
            "textract": self.textract_path,
            "html": self.html_path,
        }
        document = Document.model_validate_json(self.document_path.read_bytes())
        self._lock = RLock()
        self._head_path = self.data_dir / "head.json"
        self._download_path = self.data_dir / "downloads.json"

        source = document.source
        if source.bucket is None or source.key is None:
            raise LocalHarnessError(
                "DOCUMENT_SOURCE_NOT_S3_COMPATIBLE: bucket and key are required"
            )
        source_hash = sha256_file(self.source_path)
        if source.checksum_sha256 is not None and source.checksum_sha256 != source_hash:
            raise LocalHarnessError(
                "SOURCE_CHECKSUM_MISMATCH: supplied PDF does not match document.json provenance"
            )
        if initialize_manifest:
            ensure_manifest(self.data_dir, self.inputs)
        source_version = source.version or f"local-sha256:{source_hash}"
        self.source = S3Source(
            bucket=source.bucket,
            key=source.key,
            region="local",
            version=source_version,
            checksum_sha256=source.checksum_sha256 or source_hash,
            etag=source.etag,
        )
        self.baseline = self._input_artifact(
            "document.json", self.document_path, "application/json"
        )
        self.raw = self._input_artifact("textract.json", self.textract_path, "application/json")
        self.original_html = self._input_artifact("document.html", self.html_path, "text/html")
        now = 2_000_000_000
        self.job = Job(
            id=JOB_ID,
            owner=OWNER,
            filename=self.source_path.name,
            phase=document.status,
            created_at=now,
            updated_at=now,
            expires_at=now + 10 * 365 * 24 * 60 * 60,
            expected_bytes=self.source_path.stat().st_size,
            source=self.source,
            pages_available=document.declared_pages or len(document.pages),
            warning_count=len(document.warnings),
            raw=self.raw,
            artifacts={
                "document.json": self.baseline,
                "document.html": self.original_html,
            },
        )

    @staticmethod
    def _input_artifact(name: str, path: Path, content_type: str) -> Artifact:
        return Artifact(
            key=f"local-input/{name}",
            version=f"sha256:{sha256_file(path)}",
            content_type=content_type,
        )

    def get(self, job_id: str) -> Job | ReviewHead | None:
        """Satisfy JobSource and ReviewStore; head wins for the fixed job after creation."""
        if job_id != JOB_ID:
            return None
        head = self.get_head(job_id)
        return head if head is not None else self.job

    def get_job(self, job_id: str) -> Job | None:
        return self.job if job_id == JOB_ID else None

    def get_head(self, job_id: str) -> ReviewHead | None:
        if job_id != JOB_ID or not self._head_path.exists():
            return None
        try:
            return ReviewHead.model_validate_json(self._head_path.read_bytes())
        except (OSError, ValueError) as error:
            raise LocalHarnessError(f"INVALID_LOCAL_HEAD: {self._head_path}") from error

    def publish(self, head: ReviewHead, expected_revision: str | None) -> bool:
        with self._lock:
            current = self.get_head(head.job_id)
            current_revision = current.revision_id if current is not None else None
            if current_revision != expected_revision:
                return False
            _atomic_json(self._head_path, head.model_dump(mode="json"))
            return True

    def _generated_path(self, key: str) -> Path:
        if not key.startswith("local-generated/"):
            raise LocalHarnessError("UNKNOWN_LOCAL_ARTIFACT")
        relative = Path(key.removeprefix("local-generated/"))
        path = (self.data_dir / "objects" / relative).resolve()
        root = (self.data_dir / "objects").resolve()
        if not _contains(root, path):
            raise LocalHarnessError("INVALID_LOCAL_ARTIFACT_PATH")
        return path

    def read(self, artifact: Artifact) -> bytes:
        if artifact == self.baseline:
            return self.document_path.read_bytes()
        if artifact == self.raw:
            return self.textract_path.read_bytes()
        if artifact == self.original_html:
            return self.html_path.read_bytes()
        path = self._generated_path(artifact.key)
        body = path.read_bytes()
        if artifact.version != f"sha256:{hashlib.sha256(body).hexdigest()}":
            raise LocalHarnessError("LOCAL_ARTIFACT_HASH_MISMATCH")
        return body

    def _put(self, key: str, body: bytes, content_type: str) -> Artifact:
        path = self._generated_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if path.read_bytes() != body:
                raise LocalHarnessError(f"IMMUTABLE_LOCAL_OBJECT_CONFLICT: {key}") from None
        return Artifact(
            key=key,
            version=f"sha256:{hashlib.sha256(body).hexdigest()}",
            content_type=content_type,
        )

    def put_revision(self, job_id: str, revision_id: str, body: bytes) -> Artifact:
        return self._put(
            f"local-generated/{job_id}/revisions/{revision_id}/review.json",
            body,
            "application/json",
        )

    def put_export(
        self,
        job_id: str,
        revision_id: str,
        format: Literal["html", "json"],
        body: bytes,
    ) -> Artifact:
        content_type = "text/html" if format == "html" else "application/json"
        return self._put(
            f"local-generated/{job_id}/revisions/{revision_id}/exports/document.{format}",
            body,
            content_type,
        )

    def _downloads(self) -> dict[str, dict[str, str]]:
        if not self._download_path.exists():
            return {}
        try:
            loaded = json.loads(self._download_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise LocalHarnessError("INVALID_LOCAL_DOWNLOAD_REGISTRY") from error
        if not isinstance(loaded, dict):
            raise LocalHarnessError("INVALID_LOCAL_DOWNLOAD_REGISTRY")
        return cast(dict[str, dict[str, str]], loaded)

    def download(self, artifact: Artifact, filename: str) -> str:
        # The random capability is persisted, opaque, and tied to one immutable artifact.
        with self._lock:
            downloads = self._downloads()
            existing = next(
                (
                    token
                    for token, entry in downloads.items()
                    if entry.get("artifact") == artifact.model_dump_json()
                    and entry.get("filename") == filename
                ),
                None,
            )
            token = existing or secrets.token_urlsafe(32)
            if existing is None:
                downloads[token] = {
                    "artifact": artifact.model_dump_json(),
                    "filename": filename,
                }
                _atomic_json(self._download_path, downloads)
        return f"/documents/local-review/downloads/{token}"

    def download_bytes(self, token: str) -> tuple[bytes, Artifact, str] | None:
        entry = self._downloads().get(token)
        if entry is None:
            return None
        try:
            artifact = Artifact.model_validate_json(entry["artifact"])
            filename = entry["filename"]
            return self.read(artifact), artifact, filename
        except (KeyError, ValueError):
            raise LocalHarnessError("INVALID_LOCAL_DOWNLOAD_REGISTRY") from None

    def stream_source(self, source: S3Source) -> Iterable[bytes]:
        if source != self.source:
            raise LocalHarnessError("UNKNOWN_LOCAL_SOURCE")

        def chunks() -> Iterator[bytes]:
            with self.source_path.open("rb") as stream:
                yield from iter(lambda: stream.read(64 * 1024), b"")

        return chunks()


class LocalJobs:
    """Unambiguous JobSource facade over the combined persistent adapter."""

    def __init__(self, store: LocalReviewStore) -> None:
        self.store = store

    def get(self, job_id: str) -> Job | None:
        return self.store.get_job(job_id)


class LocalHeads:
    """Unambiguous ReviewStore facade over the combined persistent adapter."""

    def __init__(self, store: LocalReviewStore) -> None:
        self.store = store

    def get(self, job_id: str) -> ReviewHead | None:
        return self.store.get_head(job_id)

    def publish(self, head: ReviewHead, expected_revision: str | None) -> bool:
        return self.store.publish(head, expected_revision)

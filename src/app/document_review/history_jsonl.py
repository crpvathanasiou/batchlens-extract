"""Atomic derived ``history.jsonl`` materialisation of a B1 projection.

The published ``ReviewHead`` and reachable ``ReviewRevision`` envelopes remain
authoritative. This module never publishes a head, never walks a second chain,
and does not verify source/raw/export bytes.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import IO, Literal

from pydantic import ValidationError

from app.document_jobs.contracts import Artifact, Job
from app.document_review.contracts import ReviewHead, ReviewModel, ReviewRevision, RevisionId
from app.document_review.history import (
    CommittedHistoryProjection,
    HistoryCoverage,
    HistoryInputs,
    HistoryRevisionRecord,
    project_committed_history,
)

HISTORY_JSONL_SCHEMA = "batchlens.committed-history.jsonl.v1"
HistoryFileStatus = Literal["CURRENT", "STALE", "INVALID_OR_MISSING"]


class HistoryJsonlError(RuntimeError):
    """Inspectable materialisation or validation failure. Not an HTTP adapter."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class HistoryJsonlCoverageRecord(ReviewModel):
    """First JSONL line. Embedded B1 coverage states through which revision it is complete."""

    kind: Literal["HISTORY_COVERAGE"] = "HISTORY_COVERAGE"
    schema_name: Literal["batchlens.committed-history.jsonl.v1"] = HISTORY_JSONL_SCHEMA
    schema_version: Literal[1] = 1
    coverage: HistoryCoverage
    inputs: HistoryInputs


class HistoryJsonlFile(ReviewModel):
    coverage: HistoryCoverage
    inputs: HistoryInputs
    records: tuple[HistoryRevisionRecord, ...]


class HistoryJsonlWriteResult(ReviewModel):
    path: str
    coverage: HistoryCoverage


class HistoryJsonlStatusResult(ReviewModel):
    status: HistoryFileStatus
    coverage: HistoryCoverage | None = None


def materialize_history_jsonl(
    path: Path,
    job: Job,
    head: ReviewHead,
    read_revision: Callable[[Artifact], ReviewRevision],
) -> HistoryJsonlWriteResult:
    """Project via B1, then atomically replace ``path`` with one UTF-8 JSONL file.

    Raises ``ReviewError`` if the frozen chain is invalid (no replacement).
    Raises ``HistoryJsonlError`` if path preparation or durable write/replace fails.
    """

    projection = project_committed_history(job, head, read_revision)
    body = encode_history_jsonl(projection)
    write_atomic_jsonl(path, body)
    return HistoryJsonlWriteResult(path=str(path), coverage=projection.coverage)


def encode_history_jsonl(projection: CommittedHistoryProjection) -> bytes:
    header = HistoryJsonlCoverageRecord(coverage=projection.coverage, inputs=projection.inputs)
    lines = [_json_line(header.model_dump(mode="json"))]
    lines.extend(_json_line(record.model_dump(mode="json")) for record in projection.records)
    return ("\n".join(lines) + "\n").encode("utf-8")


def read_history_jsonl(path: Path) -> HistoryJsonlFile:
    """Validate persisted bytes. Does not rebuild and does not treat tmp files as history."""

    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise HistoryJsonlError("HISTORY_JSONL_MISSING") from None
    except OSError as error:
        raise HistoryJsonlError("HISTORY_JSONL_INVALID") from error
    return parse_history_jsonl_bytes(raw)


def parse_history_jsonl_bytes(raw: bytes) -> HistoryJsonlFile:
    if not raw or not raw.endswith(b"\n"):
        raise HistoryJsonlError("HISTORY_JSONL_INVALID")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HistoryJsonlError("HISTORY_JSONL_INVALID") from error
    lines = text.split("\n")
    if lines[-1] != "":
        raise HistoryJsonlError("HISTORY_JSONL_INVALID")
    payload_lines = lines[:-1]
    if not payload_lines or any(line == "" for line in payload_lines):
        raise HistoryJsonlError("HISTORY_JSONL_INVALID")
    try:
        parsed_rows = tuple(json.loads(line) for line in payload_lines)
    except ValueError as error:
        raise HistoryJsonlError("HISTORY_JSONL_INVALID") from error
    if any(not isinstance(row, dict) for row in parsed_rows):
        raise HistoryJsonlError("HISTORY_JSONL_INVALID")
    header_row = parsed_rows[0]
    if header_row.get("kind") != "HISTORY_COVERAGE":
        raise HistoryJsonlError("HISTORY_JSONL_INVALID")
    try:
        header = HistoryJsonlCoverageRecord.model_validate(header_row)
        records = tuple(HistoryRevisionRecord.model_validate(row) for row in parsed_rows[1:])
    except (ValidationError, ValueError, TypeError) as error:
        raise HistoryJsonlError("HISTORY_JSONL_INVALID") from error
    _check_records_match_coverage(header.coverage, records)
    return HistoryJsonlFile(coverage=header.coverage, inputs=header.inputs, records=records)


def history_jsonl_status(
    path: Path, expected: ReviewHead | HistoryCoverage
) -> HistoryJsonlStatusResult:
    """Compare a valid file's coverage to a frozen head or B1 coverage. Never rebuilds."""

    try:
        parsed = read_history_jsonl(path)
    except HistoryJsonlError:
        return HistoryJsonlStatusResult(status="INVALID_OR_MISSING")
    expected_id, expected_generation = _expected_identity(expected)
    coverage = parsed.coverage
    if (
        coverage.head_revision_id == expected_id
        and coverage.head_generation == expected_generation
        and coverage.complete_through_revision_id == expected_id
        and coverage.complete_through_generation == expected_generation
    ):
        return HistoryJsonlStatusResult(status="CURRENT", coverage=coverage)
    return HistoryJsonlStatusResult(status="STALE", coverage=coverage)


def write_atomic_jsonl(path: Path, body: bytes) -> None:
    """Same-directory exclusive temp, fsync, then replace. Does not delete the final file first.

    Any OSError while resolving the path, creating the parent directory, or
    creating/writing/fsyncing/replacing the temporary file is
    ``HISTORY_JSONL_WRITE_FAILED``. After a successful replace, leftover-temp
    cleanup is best-effort and cannot recast success as write failure.
    """

    temporary: Path | None = None
    try:
        path = path.resolve()
        _ensure_parent_directory(path.parent)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
        _durable_write(temporary, body)
        _replace(temporary, path)
    except OSError as error:
        raise HistoryJsonlError("HISTORY_JSONL_WRITE_FAILED") from error
    finally:
        _best_effort_unlink(temporary)


def _ensure_parent_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)


def _open_exclusive(temporary: Path) -> IO[bytes]:
    return temporary.open("xb")


def _durable_write(temporary: Path, body: bytes) -> None:
    with _open_exclusive(temporary) as stream:
        stream.write(body)
        stream.flush()
        _fsync(stream.fileno())


def _best_effort_unlink(temporary: Path | None) -> None:
    if temporary is None:
        return
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        return


def _fsync(fd: int) -> None:
    os.fsync(fd)


def _replace(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _json_line(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _expected_identity(expected: ReviewHead | HistoryCoverage) -> tuple[RevisionId, int]:
    if isinstance(expected, ReviewHead):
        return expected.revision_id, expected.generation
    return expected.head_revision_id, expected.head_generation


def _check_records_match_coverage(
    coverage: HistoryCoverage, records: tuple[HistoryRevisionRecord, ...]
) -> None:
    count = len(records)
    if (
        count == 0
        or coverage.projected_revision_count != count
        or coverage.head_generation != count
        or coverage.complete_through_generation != count
        or coverage.head_revision_id != coverage.complete_through_revision_id
        or coverage.complete_through_revision_id != records[-1].revision_id
        or coverage.complete_through_generation != records[-1].generation
        or coverage.head_revision_id != records[-1].revision_id
        or coverage.head_generation != records[-1].generation
        or records[0].parent_revision_id is not None
        or records[0].generation != 1
    ):
        raise HistoryJsonlError("HISTORY_JSONL_INVALID")
    seen: set[str] = set()
    previous: HistoryRevisionRecord | None = None
    for index, record in enumerate(records, start=1):
        if record.kind != "COMMITTED_TRANSITION" or record.generation != index:
            raise HistoryJsonlError("HISTORY_JSONL_INVALID")
        if record.revision_id in seen:
            raise HistoryJsonlError("HISTORY_JSONL_INVALID")
        seen.add(record.revision_id)
        if previous is None:
            previous = record
            continue
        if record.parent_revision_id != previous.revision_id:
            raise HistoryJsonlError("HISTORY_JSONL_INVALID")
        previous = record

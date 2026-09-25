"""Atomic derived history.jsonl materialisation (B2a)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from app.document_jobs.contracts import Artifact
from app.document_review.contracts import (
    RequestedChange,
    ReviewError,
    ReviewHead,
    ReviewRevision,
    ReviewState,
    UpdateReviewBody,
)
from app.document_review.history_jsonl import (
    HistoryJsonlError,
    history_jsonl_status,
    materialize_history_jsonl,
    read_history_jsonl,
    write_atomic_jsonl,
)
from app.document_review.service import ReviewService
from tests.document_review.test_backend_review import IDS, Heads, Objects, make_service


def _page_node(state: ReviewState, page_number: int):
    return next(node for node in state.catalogue.nodes if node.page_number == page_number)


def _manual_body(
    state: ReviewState,
    text: str = "page two corrected",
    *,
    expected_revision: str | None = None,
) -> UpdateReviewBody:
    return UpdateReviewBody(
        expected_revision=expected_revision,
        changes=(RequestedChange(node_id=_page_node(state, 2).node_id, text=text),),
    )


def _reader(objects: Objects) -> Callable[[Artifact], ReviewRevision]:
    def read(artifact: Artifact) -> ReviewRevision:
        return ReviewRevision.model_validate_json(objects.read(artifact))

    return read


def _write_chain(
    service: ReviewService,
    heads: Heads,
    objects: Objects,
    path: Path,
    text: str = "page two corrected",
):
    initial = service.get("job", "alice")
    first = service.update("job", "alice", _manual_body(initial, text))
    second = service.update(
        "job",
        "alice",
        _manual_body(first, f"{text} later", expected_revision=first.revision_id),
    )
    job = service.jobs.get("job")
    assert job is not None and heads.head is not None
    result = materialize_history_jsonl(path, job, heads.head, _reader(objects))
    return first, second, result


def _assert_prepare_io_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hook: str) -> None:
    import app.document_review.history_jsonl as module

    service, heads, objects = make_service(warnings=False)
    first_path = tmp_path / "first" / "history.jsonl"
    existing_path = tmp_path / "existing" / "history.jsonl"
    _write_chain(service, heads, objects, existing_path)
    original = existing_path.read_bytes()
    job = service.jobs.get("job")
    assert job is not None and heads.head is not None

    def fail_prepare(*_args: object, **_kwargs: object) -> object:
        raise OSError("prepare failed")

    monkeypatch.setattr(module, hook, fail_prepare)
    with pytest.raises(HistoryJsonlError, match="HISTORY_JSONL_WRITE_FAILED"):
        materialize_history_jsonl(first_path, job, heads.head, _reader(objects))
    assert not first_path.exists()
    assert history_jsonl_status(first_path, heads.head).status == "INVALID_OR_MISSING"
    with pytest.raises(HistoryJsonlError, match="HISTORY_JSONL_WRITE_FAILED"):
        materialize_history_jsonl(existing_path, job, heads.head, _reader(objects))
    assert existing_path.read_bytes() == original


def test_materialize_writes_header_and_chronological_records(tmp_path: Path) -> None:
    service, heads, objects = make_service(warnings=False)
    path = tmp_path / "history.jsonl"
    first, second, result = _write_chain(service, heads, objects, path)
    assert path.is_file()
    assert list(tmp_path.glob(".*.tmp")) == []
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    lines = raw.decode("utf-8").splitlines()
    assert len(lines) == 3
    header = json.loads(lines[0])
    assert header["kind"] == "HISTORY_COVERAGE"
    assert header["schema_name"] == "batchlens.committed-history.jsonl.v1"
    coverage = header["coverage"]
    assert coverage["complete_through_revision_id"] == second.revision_id
    assert coverage["complete_through_generation"] == 2
    assert coverage["projected_revision_count"] == 2
    assert coverage["evidence_limits"]["export_bytes"] == "not_verified"
    records = [json.loads(line) for line in lines[1:]]
    assert [row["kind"] for row in records] == ["COMMITTED_TRANSITION", "COMMITTED_TRANSITION"]
    assert [row["generation"] for row in records] == [1, 2]
    assert records[0]["revision_id"] == first.revision_id
    assert records[0]["parent_revision_id"] is None
    assert records[1]["parent_revision_id"] == first.revision_id
    assert "committed_at" not in records[0]
    assert "revision_created_at" in records[0]
    assert result.coverage.complete_through_revision_id == second.revision_id
    parsed = read_history_jsonl(path)
    assert first.revision is not None
    assert parsed.records[0].revision_created_at == first.revision.created_at
    assert result.path == str(path)


def test_read_back_is_current_for_exact_head(tmp_path: Path) -> None:
    service, heads, objects = make_service(warnings=False)
    path = tmp_path / "history.jsonl"
    _write_chain(service, heads, objects, path)
    head = cast(ReviewHead, heads.head)
    parsed = read_history_jsonl(path)
    assert parsed.coverage.head_revision_id == head.revision_id
    status = history_jsonl_status(path, head)
    assert status.status == "CURRENT"
    assert status.coverage == parsed.coverage


def test_earlier_file_is_stale_against_later_head(tmp_path: Path) -> None:
    service, heads, objects = make_service(warnings=False)
    path = tmp_path / "history.jsonl"
    _write_chain(service, heads, objects, path)
    earlier = cast(ReviewHead, heads.head)
    later_state = service.update(
        "job",
        "alice",
        _manual_body(service.get("job", "alice"), "third", expected_revision=earlier.revision_id),
    )
    later = cast(ReviewHead, heads.head)
    status = history_jsonl_status(path, later)
    assert status.status == "STALE"
    assert status.coverage is not None
    assert status.coverage.complete_through_revision_id == earlier.revision_id
    assert later.revision_id == later_state.revision_id
    assert history_jsonl_status(path, earlier).status == "CURRENT"


@pytest.mark.parametrize(
    "mode",
    [
        "missing",
        "empty",
        "no_header",
        "truncated",
        "count_mismatch",
        "parent_mismatch",
        "duplicate",
    ],
)
def test_invalid_or_missing_file_is_not_accepted(tmp_path: Path, mode: str) -> None:
    service, heads, objects = make_service(warnings=False)
    path = tmp_path / "history.jsonl"
    if mode == "missing":
        initial = service.get("job", "alice")
        service.update("job", "alice", _manual_body(initial))
        head = cast(ReviewHead, heads.head)
        with pytest.raises(HistoryJsonlError, match="HISTORY_JSONL_MISSING"):
            read_history_jsonl(path)
        assert history_jsonl_status(path, head).status == "INVALID_OR_MISSING"
        return
    _write_chain(service, heads, objects, path)
    head = cast(ReviewHead, heads.head)
    if mode == "empty":
        path.write_bytes(b"")
    elif mode == "no_header":
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text(lines[1] + "\n", encoding="utf-8")
    elif mode == "truncated":
        path.write_bytes(path.read_bytes().rstrip(b"\n")[:-8])
    elif mode == "count_mismatch":
        lines = path.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        header["coverage"]["projected_revision_count"] = 9
        lines[0] = json.dumps(header, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif mode == "parent_mismatch":
        lines = path.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[2])
        row["parent_revision_id"] = row["revision_id"]
        lines[2] = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        lines = path.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[2])
        row["revision_id"] = json.loads(lines[1])["revision_id"]
        lines[2] = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(HistoryJsonlError, match="HISTORY_JSONL_INVALID"):
        read_history_jsonl(path)
    assert history_jsonl_status(path, head).status == "INVALID_OR_MISSING"


def test_write_failures_preserve_prior_final_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.document_review.history_jsonl as module

    service, heads, objects = make_service(warnings=False)
    path = tmp_path / "history.jsonl"
    _write_chain(service, heads, objects, path)
    original = path.read_bytes()
    job = service.jobs.get("job")
    assert job is not None and heads.head is not None

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("write failed")

    monkeypatch.setattr(module, "_durable_write", fail_write)
    with pytest.raises(HistoryJsonlError, match="HISTORY_JSONL_WRITE_FAILED"):
        materialize_history_jsonl(path, job, heads.head, _reader(objects))
    assert path.read_bytes() == original
    monkeypatch.undo()

    def fail_fsync(_fd: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(module, "_fsync", fail_fsync)
    with pytest.raises(HistoryJsonlError, match="HISTORY_JSONL_WRITE_FAILED"):
        materialize_history_jsonl(path, job, heads.head, _reader(objects))
    assert path.read_bytes() == original
    monkeypatch.undo()

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(module, "_replace", fail_replace)
    with pytest.raises(HistoryJsonlError, match="HISTORY_JSONL_WRITE_FAILED"):
        materialize_history_jsonl(path, job, heads.head, _reader(objects))
    assert path.read_bytes() == original
    assert list(tmp_path.glob(".*.tmp")) == []


def test_parent_directory_creation_failure_is_write_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_prepare_io_failure(tmp_path, monkeypatch, "_ensure_parent_directory")


def test_temporary_file_creation_failure_is_write_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_prepare_io_failure(tmp_path, monkeypatch, "_open_exclusive")


def test_failed_first_write_does_not_create_complete_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.document_review.history_jsonl as module

    service, heads, objects = make_service(warnings=False)
    initial = service.get("job", "alice")
    service.update("job", "alice", _manual_body(initial))
    path = tmp_path / "history.jsonl"
    job = service.jobs.get("job")
    assert job is not None and heads.head is not None

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("write failed")

    monkeypatch.setattr(module, "_durable_write", fail_write)
    with pytest.raises(HistoryJsonlError, match="HISTORY_JSONL_WRITE_FAILED"):
        materialize_history_jsonl(path, job, heads.head, _reader(objects))
    assert not path.exists()
    assert history_jsonl_status(path, heads.head).status == "INVALID_OR_MISSING"


def test_b1_chain_failure_does_not_replace_existing_file(tmp_path: Path) -> None:
    service, heads, objects = make_service(warnings=False)
    path = tmp_path / "history.jsonl"
    _write_chain(service, heads, objects, path)
    original = path.read_bytes()
    revision = service.get("job", "alice").revision
    assert revision is not None and revision.parent is not None
    objects.data.pop((revision.parent.key, revision.parent.version))
    job = service.jobs.get("job")
    assert job is not None and heads.head is not None
    with pytest.raises(ReviewError, match="INVALID_REVIEW_STATE"):
        materialize_history_jsonl(path, job, heads.head, _reader(objects))
    assert path.read_bytes() == original


def test_unreachable_candidate_is_not_materialised(tmp_path: Path) -> None:
    service, heads, objects = make_service(warnings=False)
    initial = service.get("job", "alice")
    saved = service.update("job", "alice", _manual_body(initial))
    objects.put_revision("job", IDS[10], b'{"not":"committed"}')
    path = tmp_path / "history.jsonl"
    job = service.jobs.get("job")
    assert job is not None and heads.head is not None
    materialize_history_jsonl(path, job, heads.head, _reader(objects))
    parsed = read_history_jsonl(path)
    assert parsed.coverage.projected_revision_count == 1
    assert parsed.records[0].revision_id == saved.revision_id
    assert IDS[10] not in {record.revision_id for record in parsed.records}
    leftover = tmp_path / ".history.jsonl.ignored.tmp"
    leftover.write_text("not-history\n", encoding="utf-8")
    assert read_history_jsonl(path).records[0].revision_id == saved.revision_id
    assert history_jsonl_status(leftover, heads.head).status == "INVALID_OR_MISSING"


def test_atomic_helper_rejects_incomplete_bytes(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    write_atomic_jsonl(path, b'{"kind":"HISTORY_COVERAGE"}\n')
    with pytest.raises(HistoryJsonlError, match="HISTORY_JSONL_INVALID"):
        read_history_jsonl(path)

"""Local-harness derived history.jsonl rebuild after published heads (B2b)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from app.document_jobs.contracts import Artifact, Job
from app.document_review.contracts import ReviewHead, ReviewRevision
from app.document_review.history_jsonl import (
    HistoryJsonlError,
    HistoryJsonlWriteResult,
    history_jsonl_status,
    read_history_jsonl,
)
from tests.document_review.local_harness import TOKEN, create_app
from tests.document_review.local_store import JOB_ID, LocalHarnessError, LocalReviewStore
from tests.document_review.test_local_harness import local_review_headers, local_review_paths


def _client(paths: dict[str, Path]) -> TestClient:
    return TestClient(create_app(**paths))


def _review_path() -> str:
    return f"/api/v1/documents/jobs/{JOB_ID}/review"


def _headers() -> dict[str, str]:
    return local_review_headers()


def _tracking_materialize(
    calls: list[int], real: Callable[..., HistoryJsonlWriteResult]
) -> Callable[..., HistoryJsonlWriteResult]:
    def spy(
        path: Path,
        job: Job,
        head: ReviewHead,
        read_revision: Callable[[Artifact], ReviewRevision],
    ) -> HistoryJsonlWriteResult:
        calls.append(1)
        return real(path, job, head, read_revision)

    return spy


def _save(
    client: TestClient,
    node_id: str,
    text: str,
    expected_revision: str | None,
    *,
    finding_id: str | None = None,
):
    decisions: list[dict[str, str]] = []
    if finding_id is not None:
        decisions.append(
            {
                "finding_id": finding_id,
                "action": "ACKNOWLEDGED_LIMITATION",
                "note": "local history test",
            }
        )
    return client.put(
        _review_path(),
        headers=_headers(),
        json={
            "expected_revision": expected_revision,
            "changes": [{"node_id": node_id, "text": text}],
            "decisions": decisions,
        },
    )


def _open_store(paths: dict[str, Path]) -> LocalReviewStore:
    return LocalReviewStore(
        paths["data_dir"],
        paths["source"],
        paths["document"],
        paths["textract"],
        paths["html"],
    )


def _revision_files(data_dir: Path) -> list[Path]:
    root = data_dir / "objects" / JOB_ID / "revisions"
    if not root.exists():
        return []
    return sorted(root.glob("*/review.json"))


def test_fresh_store_without_head_does_not_create_history(tmp_path: Path) -> None:
    paths = local_review_paths(tmp_path)
    store = _open_store(paths)
    assert store.get_head(JOB_ID) is None
    assert store.history_path == paths["data_dir"].resolve() / "history.jsonl"
    assert not store.history_path.exists()


def test_successful_save_publishes_current_history(tmp_path: Path) -> None:
    paths = local_review_paths(tmp_path)
    client = _client(paths)
    state = client.get(_review_path(), headers=_headers()).json()
    saved = _save(
        client,
        state["catalogue"]["nodes"][0]["node_id"],
        "First correction",
        None,
        finding_id=state["findings"][0]["finding_id"],
    )
    assert saved.status_code == 200
    assert "receipt" not in saved.json()
    assert saved.json()["revision_id"]
    store = _open_store(paths)
    head = cast(ReviewHead, store.get_head(JOB_ID))
    assert history_jsonl_status(store.history_path, head).status == "CURRENT"
    parsed = read_history_jsonl(store.history_path)
    assert parsed.coverage.complete_through_revision_id == head.revision_id
    assert parsed.coverage.complete_through_generation == head.generation
    assert parsed.records[-1].revision_id == head.revision_id


def test_approvals_and_invalidation_reach_current_head(tmp_path: Path) -> None:
    paths = local_review_paths(tmp_path)
    client = _client(paths)
    state = client.get(_review_path(), headers=_headers()).json()
    node_id = state["catalogue"]["nodes"][0]["node_id"]
    finding_id = state["findings"][0]["finding_id"]
    first = _save(client, node_id, "First correction", None, finding_id=finding_id)
    assert first.status_code == 200
    first_id = first.json()["revision_id"]
    page = client.post(
        f"{_review_path()}/pages/1/approve",
        headers=_headers(),
        json={"expected_revision": first_id},
    )
    assert page.status_code == 200
    edited = _save(
        client, node_id, "Second correction", page.json()["revision_id"], finding_id=finding_id
    )
    assert edited.status_code == 200
    assert edited.json()["pages"][0]["approval"] is None
    page_again = client.post(
        f"{_review_path()}/pages/1/approve",
        headers=_headers(),
        json={"expected_revision": edited.json()["revision_id"]},
    )
    assert page_again.status_code == 200
    approved = client.post(
        f"{_review_path()}/approve",
        headers=_headers(),
        json={"expected_revision": page_again.json()["revision_id"]},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    store = _open_store(paths)
    head = cast(ReviewHead, store.get_head(JOB_ID))
    parsed = read_history_jsonl(store.history_path)
    assert history_jsonl_status(store.history_path, head).status == "CURRENT"
    assert parsed.coverage.complete_through_revision_id == head.revision_id
    assert parsed.coverage.complete_through_generation == head.generation
    assert parsed.records[-1].action == "DOCUMENT_APPROVED"
    assert parsed.records[-1].exports is not None
    assert any(record.page_approvals_invalidated for record in parsed.records)
    assert {record.action for record in parsed.records} >= {
        "DRAFT_SAVED",
        "PAGE_APPROVED",
        "DOCUMENT_APPROVED",
    }


def test_restart_rebuilds_only_when_history_is_not_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tests.document_review.local_store as module

    paths = local_review_paths(tmp_path)
    client = _client(paths)
    state = client.get(_review_path(), headers=_headers()).json()
    node_id = state["catalogue"]["nodes"][0]["node_id"]
    first = _save(client, node_id, "First correction", None)
    assert first.status_code == 200
    history_path = paths["data_dir"] / "history.jsonl"
    generation_one = history_path.read_bytes()
    first_id = first.json()["revision_id"]
    calls: list[int] = []
    monkeypatch.setattr(
        module,
        "materialize_history_jsonl",
        _tracking_materialize(calls, module.materialize_history_jsonl),
    )
    _client(paths)
    assert calls == []
    assert history_path.read_bytes() == generation_one

    history_path.unlink()
    missing_restart = _client(paths)
    assert len(calls) == 1
    head = ReviewHead.model_validate_json((paths["data_dir"] / "head.json").read_bytes())
    assert history_jsonl_status(history_path, head).status == "CURRENT"

    later = _save(missing_restart, node_id, "Later correction", first_id)
    assert later.status_code == 200
    generation_two = history_path.read_bytes()
    history_path.write_bytes(generation_one)
    calls.clear()
    _client(paths)
    assert len(calls) == 1
    later_head = ReviewHead.model_validate_json((paths["data_dir"] / "head.json").read_bytes())
    assert history_jsonl_status(history_path, later_head).status == "CURRENT"
    assert history_path.read_bytes() == generation_two

    history_path.write_text("{not-json\n", encoding="utf-8")
    calls.clear()
    _client(paths)
    assert len(calls) == 1
    assert history_jsonl_status(history_path, later_head).status == "CURRENT"
    assert history_path.read_bytes() == generation_two


def test_materialisation_failure_after_publish_keeps_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import tests.document_review.local_store as module

    paths = local_review_paths(tmp_path)
    client = _client(paths)
    state = client.get(_review_path(), headers=_headers()).json()
    node_id = state["catalogue"]["nodes"][0]["node_id"]
    first = _save(client, node_id, "First correction", None)
    assert first.status_code == 200
    first_id = first.json()["revision_id"]
    history_path = paths["data_dir"] / "history.jsonl"
    prior = history_path.read_bytes()

    def fail_materialize(*_args: object, **_kwargs: object) -> None:
        raise HistoryJsonlError("HISTORY_JSONL_WRITE_FAILED")

    monkeypatch.setattr(module, "materialize_history_jsonl", fail_materialize)
    with caplog.at_level(logging.ERROR, logger="tests.document_review.local_store"):
        failed = _save(client, node_id, "Second correction", first_id)
    assert failed.status_code == 503
    assert failed.json() == {"code": "LOCAL_HISTORY_REBUILD_FAILED"}
    committed = client.get(_review_path(), headers=_headers()).json()
    assert committed["revision_id"] != first_id
    assert committed["generation"] == 2
    assert history_path.read_bytes() == prior
    assert len(_revision_files(paths["data_dir"])) == 2
    message = caplog.records[-1].getMessage()
    assert "local_history_rebuild_failed" in message
    assert "trigger=publish" in message
    assert JOB_ID in message
    assert committed["revision_id"] in message
    assert "generation=2" in message
    assert "error_code=HISTORY_JSONL_WRITE_FAILED" in message
    assert "Second correction" not in message
    assert TOKEN not in message

    monkeypatch.undo()
    restarted = _client(paths)
    restored = restarted.get(_review_path(), headers=_headers()).json()
    assert restored["revision_id"] == committed["revision_id"]
    head = ReviewHead.model_validate_json((paths["data_dir"] / "head.json").read_bytes())
    assert history_jsonl_status(history_path, head).status == "CURRENT"
    assert len(_revision_files(paths["data_dir"])) == 2


def test_first_publish_history_failure_creates_no_history_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tests.document_review.local_store as module

    paths = local_review_paths(tmp_path)
    client = _client(paths)
    state = client.get(_review_path(), headers=_headers()).json()
    history_path = paths["data_dir"] / "history.jsonl"

    def fail_materialize(*_args: object, **_kwargs: object) -> None:
        raise HistoryJsonlError("HISTORY_JSONL_WRITE_FAILED")

    monkeypatch.setattr(module, "materialize_history_jsonl", fail_materialize)
    failed = _save(client, state["catalogue"]["nodes"][0]["node_id"], "First correction", None)
    assert failed.status_code == 503
    assert failed.json() == {"code": "LOCAL_HISTORY_REBUILD_FAILED"}
    committed = client.get(_review_path(), headers=_headers()).json()
    assert committed["generation"] == 1
    assert committed["revision_id"]
    assert not history_path.exists()
    assert len(_revision_files(paths["data_dir"])) == 1


def test_publish_conflict_does_not_materialise_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tests.document_review.local_store as module

    paths = local_review_paths(tmp_path)
    client = _client(paths)
    state = client.get(_review_path(), headers=_headers()).json()
    first = _save(client, state["catalogue"]["nodes"][0]["node_id"], "First correction", None)
    assert first.status_code == 200
    history_path = paths["data_dir"] / "history.jsonl"
    prior = history_path.read_bytes()
    calls: list[int] = []
    monkeypatch.setattr(
        module,
        "materialize_history_jsonl",
        _tracking_materialize(calls, module.materialize_history_jsonl),
    )
    stale = client.put(
        _review_path(),
        headers=_headers(),
        json={"expected_revision": None, "changes": [], "decisions": []},
    )
    assert stale.status_code == 409
    assert stale.json() == {"code": "REVIEW_CONFLICT"}
    assert calls == []
    assert history_path.read_bytes() == prior
    assert len(_revision_files(paths["data_dir"])) == 1


@pytest.mark.parametrize("mode", ["invalid", "missing"])
def test_invalid_revision_during_rebuild_preserves_history(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, mode: str
) -> None:
    paths = local_review_paths(tmp_path)
    client = _client(paths)
    state = client.get(_review_path(), headers=_headers()).json()
    node_id = state["catalogue"]["nodes"][0]["node_id"]
    first = _save(client, node_id, "First correction", None)
    assert first.status_code == 200
    history_path = paths["data_dir"] / "history.jsonl"
    generation_one = history_path.read_bytes()
    second = _save(client, node_id, "Second correction", first.json()["revision_id"])
    assert second.status_code == 200
    second_revision = next(
        path
        for path in _revision_files(paths["data_dir"])
        if path.parent.name == second.json()["revision_id"]
    )
    history_path.write_bytes(generation_one)
    if mode == "missing":
        second_revision.unlink()
    else:
        second_revision.write_bytes(b"{not-a-revision")
    with caplog.at_level(logging.ERROR, logger="tests.document_review.local_store"):
        with pytest.raises(LocalHarnessError, match="LOCAL_HISTORY_REBUILD_FAILED"):
            _open_store(paths)
    assert history_path.read_bytes() == generation_one
    assert "local_history_rebuild_failed" in caplog.text
    assert "trigger=startup" in caplog.text
    assert "First correction" not in caplog.text
    assert "Second correction" not in caplog.text

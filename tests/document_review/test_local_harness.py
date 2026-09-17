"""Persistent local harness integration tests against the real review routes."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from app.document_conversion.contracts import Document, Element, Page, Reference, Source, Warning
from tests.document_review.local_harness import LABEL, TOKEN, create_app, find_built_assets, main
from tests.document_review.local_store import (
    JOB_ID,
    OWNER,
    LocalHarnessError,
    LocalReviewStore,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path) -> dict[str, Path]:
    inputs = root / "inputs"
    inputs.mkdir()
    source_path = inputs / "record.pdf"
    document_path = inputs / "document.json"
    textract_path = inputs / "textract.json"
    html_path = inputs / "document.html"
    source_path.write_bytes(b"%PDF-1.4\nlocal-original\n%%EOF")
    fingerprint = _sha(source_path)
    source = Source(
        identity="s3://local-review-bucket/supplied/record.pdf",
        bucket="local-review-bucket",
        key="supplied/record.pdf",
        checksum_sha256=fingerprint,
    )
    document = Document(
        source=source,
        status="SUCCEEDED",
        declared_pages=1,
        pages=(
            Page(
                number=1,
                reading_order="textract_layout",
                elements=(
                    Element(
                        kind="PARAGRAPH",
                        text="Original text",
                        references=(Reference(block_id="page-one", page=1),),
                    ),
                ),
            ),
        ),
        warnings=(
            Warning(
                code="POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY",
                block_ids=("page-one",),
                pages=(1,),
            ),
        ),
    )
    document_path.write_bytes(document.model_dump_json(indent=2).encode())
    textract_path.write_text(
        json.dumps(
            {
                "DocumentMetadata": {"Pages": 1},
                "Blocks": [{"Id": "page-one", "Page": 1}],
            }
        ),
        encoding="utf-8",
    )
    html_path.write_text("<!doctype html><p>Original text</p>", encoding="utf-8")

    static = root / "built"
    (static / "assets").mkdir(parents=True)
    (static / "review.js").write_text("export function mountReviewWorkspace() {}", encoding="utf-8")
    (static / "review.css").write_text("body {}", encoding="utf-8")
    (static / "assets" / "pdf.worker-test.mjs").write_text("// worker", encoding="utf-8")
    return {
        "source": source_path,
        "document": document_path,
        "textract": textract_path,
        "html": html_path,
        "data_dir": root / "state",
        "static_dir": static,
    }


def _client(paths: dict[str, Path]) -> TestClient:
    return TestClient(create_app(**paths))


def _headers(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_startup_reports_every_missing_absolute_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = [tmp_path / name for name in ("a.pdf", "b.json", "c.json", "d.html")]
    result = main(
        [
            "--source",
            str(missing[0]),
            "--document",
            str(missing[1]),
            "--textract",
            str(missing[2]),
            "--html",
            str(missing[3]),
            "--data-dir",
            str(tmp_path / "state"),
        ]
    )
    error = capsys.readouterr().err
    assert result != 0
    assert all(str(path.resolve()) in error for path in missing)


def test_missing_frontend_build_reports_exact_commands(tmp_path: Path) -> None:
    with pytest.raises(LocalHarnessError) as captured:
        find_built_assets(tmp_path / "missing-build")
    message = str(captured.value)
    assert "npm --prefix frontend ci" in message
    assert "npm --prefix frontend run build" in message


def test_manifest_rejects_changed_input_and_overlapping_data_dir(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    LocalReviewStore(
        paths["data_dir"],
        paths["source"],
        paths["document"],
        paths["textract"],
        paths["html"],
    )
    paths["html"].write_text("<p>changed</p>", encoding="utf-8")
    with pytest.raises(LocalHarnessError, match="use a different --data-dir"):
        LocalReviewStore(
            paths["data_dir"],
            paths["source"],
            paths["document"],
            paths["textract"],
            paths["html"],
        )
    with pytest.raises(LocalHarnessError, match="OVERLAPS"):
        LocalReviewStore(
            paths["source"].parent,
            paths["source"],
            paths["document"],
            paths["textract"],
            paths["html"],
        )


def test_real_routes_persist_restart_history_and_originals(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    original_hashes = {
        name: _sha(paths[name]) for name in ("source", "document", "textract", "html")
    }
    client = _client(paths)
    review_path = f"/api/v1/documents/jobs/{JOB_ID}/review"

    assert client.get(review_path).status_code == 401
    assert client.get(review_path, headers=_headers("wrong")).status_code == 401
    initial = client.get(review_path, headers=_headers())
    assert initial.status_code == 200
    state = initial.json()
    assert state["status"] == "NOT_REVIEWED"
    node_id = state["catalogue"]["nodes"][0]["node_id"]
    finding_id = state["findings"][0]["finding_id"]

    saved = client.put(
        review_path,
        headers=_headers(),
        json={
            "expected_revision": None,
            "changes": [{"node_id": node_id, "text": "First correction"}],
            "decisions": [
                {
                    "finding_id": finding_id,
                    "action": "ACKNOWLEDGED_LIMITATION",
                    "note": "Reviewed in the local harness",
                }
            ],
        },
    )
    assert saved.status_code == 200
    first = saved.json()
    assert first["findings"][0]["decision"]["action"] == "ACKNOWLEDGED_LIMITATION"
    first_id = cast(str, first["revision_id"])
    stale = client.put(
        review_path,
        headers=_headers(),
        json={"expected_revision": None, "changes": [], "decisions": []},
    )
    assert stale.status_code == 409 and stale.json() == {"code": "REVIEW_CONFLICT"}

    page = client.post(
        f"{review_path}/pages/1/approve",
        headers=_headers(),
        json={"expected_revision": first_id},
    )
    assert page.status_code == 200
    approved = client.post(
        f"{review_path}/approve",
        headers=_headers(),
        json={"expected_revision": page.json()["revision_id"]},
    )
    assert approved.status_code == 200
    approved_state = approved.json()
    approved_id = cast(str, approved_state["revision_id"])
    assert approved_state["status"] == "APPROVED"

    export = client.get(f"{review_path}/revisions/{approved_id}/exports/json", headers=_headers())
    assert export.status_code == 200
    download_url = export.json()["url"]
    downloaded = client.get(download_url)
    assert downloaded.status_code == 200
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert json.loads(downloaded.content)["document"]["pages"][0]["elements"][0]["text"] == (
        "First correction"
    )
    source = client.get(f"/api/v1/documents/jobs/{JOB_ID}/source", headers=_headers())
    assert source.content == paths["source"].read_bytes()

    # A fresh store/service/app has no process-global authoritative state.
    restarted = _client(paths)
    restored = restarted.get(review_path, headers=_headers()).json()
    assert restored["revision_id"] == approved_id
    assert restored["document"]["pages"][0]["elements"][0]["text"] == "First correction"
    assert restored["pages"][0]["approval"] is not None
    assert restarted.get(download_url).content == downloaded.content

    reopened = restarted.put(
        review_path,
        headers=_headers(),
        json={
            "expected_revision": approved_id,
            "changes": [{"node_id": node_id, "text": "Second correction"}],
            "decisions": [],
        },
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "IN_REVIEW"
    assert reopened.json()["pages"][0]["approval"] is None
    assert restarted.get(download_url).content == downloaded.content
    assert {name: _sha(paths[name]) for name in original_hashes} == original_hashes

    html = restarted.get("/documents/local-review")
    assert LABEL in html.text
    assert "localDemo: true" in restarted.get("/documents/local-review/bootstrap.js").text
    assert html.headers["cache-control"] == "no-store"
    assert "content-security-policy" in html.headers
    store = LocalReviewStore(
        paths["data_dir"],
        paths["source"],
        paths["document"],
        paths["textract"],
        paths["html"],
    )
    assert store.source.version == f"local-sha256:{original_hashes['source']}"
    assert store.job.owner == OWNER


def test_concurrent_first_save_has_one_winner(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    app = create_app(**paths)
    review_path = f"/api/v1/documents/jobs/{JOB_ID}/review"
    with TestClient(app) as client:
        state = client.get(review_path, headers=_headers()).json()
        node_id = state["catalogue"]["nodes"][0]["node_id"]

    def save(text: str) -> int:
        with TestClient(app) as client:
            return client.put(
                review_path,
                headers=_headers(),
                json={
                    "expected_revision": None,
                    "changes": [{"node_id": node_id, "text": text}],
                    "decisions": [],
                },
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(save, ("first", "second")))
    assert statuses == [200, 409]

    restarted = _client(paths)
    committed = restarted.get(review_path, headers=_headers()).json()
    assert committed["document"]["pages"][0]["elements"][0]["text"] in {"first", "second"}


def test_does_not_construct_aws_clients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import boto3

    paths = _fixture(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("AWS client construction is forbidden")

    monkeypatch.setattr(boto3, "client", forbidden)
    client = _client(paths)
    assert (
        client.get(f"/api/v1/documents/jobs/{JOB_ID}/review", headers=_headers()).status_code == 200
    )

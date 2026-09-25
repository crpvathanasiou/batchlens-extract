"""Review-storage context, sidecar identity, and file-backed lookup recovery."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.document_reviews import install_errors, router
from app.api.documents import install_errors as install_job_errors
from app.document_jobs.settings import DocumentSettings
from app.document_review.contracts import (
    RequestedChange,
    ReviewError,
    UpdateReviewBody,
    production_storage_namespace,
)
from app.document_review.service import ReviewService
from tests.document_review.local_harness import LocalAuth
from tests.document_review.local_store import (
    JOB_ID,
    OWNER,
    LocalHarnessError,
    LocalHeads,
    LocalJobs,
    LocalReviewStore,
    ensure_manifest,
    load_review_storage_namespace,
)
from tests.document_review.test_backend_review import make_service
from tests.document_review.test_local_harness import local_review_headers, local_review_paths


def _settings(**overrides: str) -> DocumentSettings:
    values = {
        "region": "eu-west-1",
        "bucket": "records-bucket",
        "table": "review-table",
        "queue_url": "https://sqs.example/q",
        "dlq_url": "https://sqs.example/d",
        "cognito_pool_id": "eu-west-1_pool",
        "cognito_client_id": "client",
        "origin": "https://app.example",
        "prefix": "documents",
        **overrides,
    }
    return DocumentSettings.model_validate(values)


def test_production_namespace_separates_configured_stores() -> None:
    first = production_storage_namespace(
        region="eu-west-1",
        table="table-a",
        bucket="bucket-aaa",
        prefix="documents",
        cognito_pool_id="pool-a",
    )
    same = production_storage_namespace(
        region="eu-west-1",
        table="table-a",
        bucket="bucket-aaa",
        prefix="documents",
        cognito_pool_id="pool-a",
    )
    other = production_storage_namespace(
        region="eu-west-1",
        table="table-b",
        bucket="bucket-aaa",
        prefix="documents",
        cognito_pool_id="pool-a",
    )
    assert first == same
    assert first != other
    assert len(first) == 64
    settings = _settings()
    composed = production_storage_namespace(
        region=settings.region,
        table=settings.table,
        bucket=settings.bucket,
        prefix=settings.prefix,
        cognito_pool_id=settings.cognito_pool_id,
    )
    assert composed != first


def test_sidecar_stable_across_restart_and_distinct_for_fresh_dirs(tmp_path: Path) -> None:
    paths = local_review_paths(tmp_path)
    first = LocalReviewStore(
        paths["data_dir"],
        paths["source"],
        paths["document"],
        paths["textract"],
        paths["html"],
    )
    sidecar = paths["data_dir"] / "review-context.json"
    assert sidecar.is_file()
    stored = json.loads(sidecar.read_text(encoding="utf-8"))
    restarted = LocalReviewStore(
        paths["data_dir"],
        paths["source"],
        paths["document"],
        paths["textract"],
        paths["html"],
    )
    assert first.storage_namespace == restarted.storage_namespace == stored["storage_id"]
    assert json.loads(sidecar.read_text(encoding="utf-8")) == stored
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = local_review_paths(other_root)
    second = LocalReviewStore(
        other["data_dir"],
        other["source"],
        other["document"],
        other["textract"],
        other["html"],
    )
    assert first.storage_namespace != second.storage_namespace


def test_legacy_sidecar_create_preserves_manifest_and_corrupt_fails(tmp_path: Path) -> None:
    paths = local_review_paths(tmp_path)
    inputs = {name: paths[name] for name in ("source", "document", "textract", "html")}
    ensure_manifest(paths["data_dir"], inputs)
    manifest = (paths["data_dir"] / "manifest.json").read_bytes()
    store = LocalReviewStore(
        paths["data_dir"],
        paths["source"],
        paths["document"],
        paths["textract"],
        paths["html"],
    )
    assert (paths["data_dir"] / "manifest.json").read_bytes() == manifest
    assert store.storage_namespace is not None
    (paths["data_dir"] / "review-context.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(LocalHarnessError, match="INVALID_REVIEW_CONTEXT"):
        LocalReviewStore(
            paths["data_dir"],
            paths["source"],
            paths["document"],
            paths["textract"],
            paths["html"],
        )
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    empty = LocalReviewStore(
        readonly,
        paths["source"],
        paths["document"],
        paths["textract"],
        paths["html"],
        initialize_manifest=False,
    )
    assert empty.storage_namespace is None
    assert not (readonly / "review-context.json").exists()
    assert load_review_storage_namespace(readonly, initialize=False) is None


def test_context_separates_jobs_and_rejects_other_actor() -> None:
    alice, _, _ = make_service(storage_namespace="store-a")
    other_namespace, _, _ = make_service(storage_namespace="store-b")
    first = alice.review_context("job", "alice")
    second = other_namespace.review_context("job", "alice")
    assert first.context_id != second.context_id
    with pytest.raises(ReviewError, match="JOB_NOT_FOUND"):
        alice.review_context("job", "bob")
    with pytest.raises(ReviewError, match="REVIEW_CONTEXT_CHANGED"):
        alice.require_matching_context("job", "alice", "b" * 64)


def test_file_backed_inflight_lookup_is_unresolved(tmp_path: Path) -> None:
    paths = local_review_paths(tmp_path)
    store = LocalReviewStore(
        paths["data_dir"],
        paths["source"],
        paths["document"],
        paths["textract"],
        paths["html"],
    )
    heads = LocalHeads(store)
    reached = Event()
    release = Event()
    original = heads.publish

    def gated(head: object, expected_revision: str | None) -> bool:
        reached.set()
        assert release.wait(timeout=5)
        return original(head, expected_revision)  # type: ignore[arg-type]

    heads.publish = gated  # type: ignore[method-assign]
    service = ReviewService(
        LocalJobs(store),
        heads,
        store,
        storage_namespace=store.storage_namespace,
    )
    app = FastAPI()
    app.state.document_review_service = service
    app.state.document_auth = LocalAuth()
    app.include_router(router)
    install_errors(app)
    install_job_errors(app)
    client = TestClient(app)
    headers = local_review_headers()
    context_id = client.get(
        f"/api/v1/documents/jobs/{JOB_ID}/review/context", headers=headers
    ).json()["context_id"]
    operation = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    outcome: list[object] = []
    initial_state = service.get(JOB_ID, OWNER)
    node_id = initial_state.catalogue.nodes[0].node_id
    body = UpdateReviewBody(
        expected_revision=None,
        changes=(RequestedChange(node_id=node_id, text="in flight"),),
        decisions=(),
        operation_id=operation,
    )

    def run() -> None:
        outcome.append(service.update_with_receipt(JOB_ID, OWNER, body))

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        assert reached.wait(timeout=5)
        looked = client.get(
            f"/api/v1/documents/jobs/{JOB_ID}/review/operations/{operation}",
            headers={**headers, "X-Review-Context": context_id},
        )
        assert looked.status_code == 200
        payload = looked.json()["reconciliation"]
        assert payload["status"] == "UNRESOLVED"
        assert payload["receipt"] is None
        assert store.get_head(JOB_ID) is None
        release.set()
        future.result(timeout=5)
    assert outcome and getattr(outcome[0], "receipt", None) is not None
    committed = client.get(
        f"/api/v1/documents/jobs/{JOB_ID}/review/operations/{operation}",
        headers={**headers, "X-Review-Context": context_id},
    ).json()["reconciliation"]
    assert committed["status"] == "COMMITTED"

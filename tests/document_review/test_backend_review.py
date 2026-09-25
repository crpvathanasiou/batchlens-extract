"""Synthetic mapping, lifecycle, history, rendering, and API review tests."""

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.document_reviews import install_errors, router
from app.api.documents import install_errors as install_job_errors
from app.document_conversion.aws import S3Source
from app.document_conversion.contracts import (
    Cell,
    Content,
    Document,
    Element,
    Page,
    Reference,
    Source,
    Warning,
)
from app.document_jobs.contracts import Artifact, Job, JobError
from app.document_review.contracts import (
    FinalApprovalBody,
    FindingDecisionRequest,
    PageApprovalBody,
    PageState,
    RequestedChange,
    ReviewError,
    ReviewHead,
    ReviewRevision,
    ReviewState,
    UpdateReviewBody,
)
from app.document_review.mapping import (
    apply_changes,
    build_catalogue,
    build_findings,
    suggested_tolerance_text,
)
from app.document_review.rendering import render_reviewed_html
from app.document_review.service import ReviewService

BASELINE = Artifact(
    key="documents/results/job/document.json",
    version="base-v1",
    content_type="application/json",
)
RAW = Artifact(
    key="documents/results/job/textract.json",
    version="raw-v1",
    content_type="application/json",
)
SOURCE = S3Source(
    bucket="records-bucket",
    key="documents/incoming/job/source.pdf",
    region="eu-west-1",
    version="pdf-v1",
)
IDS = tuple(f"00000000-0000-4000-8000-{value:012d}" for value in range(1, 20))


def synthetic_document(*, warnings: bool = True) -> Document:
    source = Source(
        identity="s3://records-bucket/documents/incoming/job/source.pdf",
        bucket=SOURCE.bucket,
        key=SOURCE.key,
        version=SOURCE.version,
    )
    return Document(
        source=source,
        status="SUCCEEDED",
        declared_pages=2,
        pages=(
            Page(
                number=1,
                reading_order="textract_layout",
                elements=(
                    Element(
                        kind="SECTION_HEADER",
                        text="Tolerance +0.1\nLine two",
                        references=(Reference(block_id="p1"),),
                        cells=(
                            Cell(
                                text="cell",
                                references=(Reference(block_id="cell"),),
                                row=1,
                                column=1,
                                row_span=2,
                                column_span=3,
                            ),
                        ),
                        titles=(Content(text="Title", references=()),),
                        footers=(Content(text="Footer", references=()),),
                        rows=2,
                        columns=3,
                    ),
                ),
            ),
            Page(
                number=2,
                reading_order="textract_layout",
                elements=(Element(kind="PARAGRAPH", text="same path page two", references=()),),
            ),
        ),
        warnings=(
            (
                Warning(
                    code="POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY",
                    block_ids=("p1",),
                    pages=(1,),
                ),
            )
            if warnings
            else ()
        ),
    )


class Jobs:
    def __init__(self, job: Job) -> None:
        self.job = job

    def get(self, job_id: str) -> Job | None:
        return self.job if job_id == self.job.id else None


class Heads:
    def __init__(self) -> None:
        self.head: ReviewHead | None = None

    def get(self, job_id: str) -> ReviewHead | None:
        return self.head if self.head and self.head.job_id == job_id else None

    def publish(self, head: ReviewHead, expected_revision: str | None) -> bool:
        if (self.head.revision_id if self.head else None) != expected_revision:
            return False
        self.head = head
        return True


class Objects:
    def __init__(self, document: Document) -> None:
        self.data: dict[tuple[str, str], bytes] = {
            (BASELINE.key, BASELINE.version): document.model_dump_json().encode(),
            (RAW.key, RAW.version): (
                b'{"DocumentMetadata":{"Pages":2},"Blocks":'
                b'[{"Id":"p1","Page":1},{"Id":"page-two","Page":2}]}'
            ),
        }
        self.writes: list[Artifact] = []
        self.source_reads = 0

    def read(self, artifact: Artifact) -> bytes:
        return self.data[(artifact.key, artifact.version)]

    def _write(self, key: str, body: bytes, content_type: str) -> Artifact:
        artifact = Artifact(key=key, version=f"v{len(self.writes) + 1}", content_type=content_type)
        self.data[(artifact.key, artifact.version)] = body
        self.writes.append(artifact)
        return artifact

    def put_revision(self, job_id: str, revision_id: str, body: bytes) -> Artifact:
        return self._write(
            f"documents/results/{job_id}/review/revisions/{revision_id}/review.json",
            body,
            "application/json",
        )

    def put_export(self, job_id: str, revision_id: str, format: str, body: bytes) -> Artifact:
        return self._write(
            f"documents/results/{job_id}/review/revisions/{revision_id}/exports/document.{format}",
            body,
            "text/html" if format == "html" else "application/json",
        )

    def download(self, artifact: Artifact, filename: str) -> str:
        return f"https://download.invalid/{artifact.version}/{filename}"

    def stream_source(self, source: S3Source) -> Iterable[bytes]:
        assert source == SOURCE
        self.source_reads += 1
        return (b"%PDF-", b"synthetic")


class Auth:
    def verify(self, token: str) -> str:
        if token != "alice":
            raise JobError("UNAUTHORIZED", 401)
        return token


def make_service(
    *, warnings: bool = True, document: Document | None = None, storage_namespace: str | None = None
) -> tuple[ReviewService, Heads, Objects]:
    document = document if document is not None else synthetic_document(warnings=warnings)
    job = Job(
        id="job",
        owner="alice",
        filename='unsafe/"record.pdf',
        phase="SUCCEEDED",
        created_at=1,
        updated_at=1,
        expires_at=999,
        expected_bytes=10,
        source=SOURCE,
        raw=RAW,
        artifacts={"document.json": BASELINE},
        pages_available=2,
    )
    heads, objects = Heads(), Objects(document)
    identifiers = iter(IDS)
    return (
        ReviewService(
            Jobs(job),
            heads,
            objects,
            clock=lambda: 1_700_000_000,
            new_revision_id=lambda: next(identifiers),
            storage_namespace=storage_namespace,
        ),
        heads,
        objects,
    )


def test_page_specific_catalogue_and_sparse_mapping_preserve_geometry() -> None:
    document = synthetic_document()
    catalogue = build_catalogue(document, BASELINE)
    assert all(node.path.startswith(f"pages[{node.page_number}]") for node in catalogue.nodes)
    assert len({node.node_id for node in catalogue.nodes}) == len(catalogue.nodes)
    page_two = next(node for node in catalogue.nodes if node.page_number == 2)
    changed, details = apply_changes(
        document,
        catalogue,
        (RequestedChange(node_id=page_two.node_id, text="corrected page two"),),
    )
    assert changed.pages[0].elements[0].text == "Tolerance +0.1\nLine two"
    assert changed.pages[1].elements[0].text == "corrected page two"
    cell = changed.pages[0].elements[0].cells[0]
    assert (cell.row_span, cell.column_span) == (2, 3)
    assert details[page_two.node_id] == ("same path page two", "corrected page two")


def test_findings_are_stable_and_raw_figure_page_falls_back() -> None:
    document = synthetic_document()
    warning = Warning(code="UNINTERPRETED_LAYOUT_FIGURE", block_ids=("figure",))
    document = document.model_copy(update={"warnings": (warning, warning)})
    catalogue = build_catalogue(document, BASELINE)
    raw: dict[str, object] = {"Blocks": [{"Id": "figure", "Page": 2}]}
    first = build_findings(document.warnings, catalogue, document, raw)
    second = build_findings(document.warnings, catalogue, document, raw)
    assert first == second
    assert first[0].finding_id != first[1].finding_id
    assert first[0].pages == (2,)


def _tolerance_suggestion(text: str) -> str:
    ref = Reference(block_id="cell-1", page=1)
    cell = Cell(text=text, references=(ref,), row=1, column=1)
    document = Document(
        source=Source(
            identity="s3://records-bucket/documents/incoming/job/source.pdf",
            bucket=SOURCE.bucket,
            key=SOURCE.key,
            version=SOURCE.version,
        ),
        status="SUCCEEDED",
        pages=(
            Page(
                number=1,
                reading_order="textract_layout",
                elements=(
                    Element(
                        kind="TABLE",
                        text="",
                        references=(ref,),
                        cells=(cell,),
                        rows=1,
                        columns=1,
                    ),
                ),
            ),
        ),
        warnings=(
            Warning(
                code="POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY",
                block_ids=("cell-1",),
                pages=(1,),
            ),
        ),
    )
    catalogue = build_catalogue(document, BASELINE)
    findings = build_findings(
        document.warnings,
        catalogue,
        document,
        {"Blocks": [{"Id": "cell-1", "Page": 1}]},
    )
    assert findings[0].suggested_replacement is not None
    return findings[0].suggested_replacement.text


def test_tolerance_suggestion_expands_isolated_abbreviation() -> None:
    assert suggested_tolerance_text("Toler +0.1%") == "Tolerance ±0.1%"
    assert suggested_tolerance_text("Toler. + 1,5") == "Tolerance ± 1,5"
    assert suggested_tolerance_text("Tolerance +0.1%") == "Tolerance ±0.1%"
    assert _tolerance_suggestion("Toler +0.1%") == "Tolerance ±0.1%"
    assert _tolerance_suggestion("Toler. + 1,5") == "Tolerance ± 1,5"
    assert _tolerance_suggestion("Tolerance +0.1%") == "Tolerance ±0.1%"


def test_lifecycle_uses_parent_artifacts_and_retains_historical_approved_exports() -> None:
    service, heads, objects = make_service()
    untouched = service.get("job", "alice")
    assert untouched.status == "NOT_REVIEWED" and not objects.writes and heads.head is None
    with pytest.raises(ReviewError, match="JOB_NOT_FOUND"):
        service.get("job", "bob")

    page_two = next(node for node in untouched.catalogue.nodes if node.page_number == 2)
    first = service.update(
        "job",
        "alice",
        UpdateReviewBody(
            expected_revision=None,
            changes=(RequestedChange(node_id=page_two.node_id, text="page two corrected"),),
        ),
    )
    assert first.status == "IN_REVIEW"
    assert first.revision is not None and first.revision.parent is None
    finding = first.findings[0]
    assert finding.suggested_replacement is not None
    assert finding.suggested_replacement.expected_region_hash == finding.region_hash
    tolerance_node = finding.node_ids[0]
    current = next(
        node for node in first.catalogue.nodes if node.node_id == tolerance_node
    ).baseline_text
    resolved = service.update(
        "job",
        "alice",
        UpdateReviewBody(
            expected_revision=cast(str, first.revision_id),
            decisions=(
                FindingDecisionRequest(
                    finding_id=finding.finding_id,
                    action="RESOLVED_AFTER_EDIT",
                    expected_region_hash=finding.region_hash,
                    replacement=RequestedChange(
                        node_id=tolerance_node, text=current.replace("+", "±", 1)
                    ),
                ),
            ),
        ),
    )
    assert resolved.findings[0].resolved
    page1 = service.approve_page(
        "job",
        "alice",
        1,
        PageApprovalBody(expected_revision=cast(str, resolved.revision_id)),
    )
    page2 = service.approve_page(
        "job",
        "alice",
        2,
        PageApprovalBody(expected_revision=cast(str, page1.revision_id)),
    )
    approved = service.approve(
        "job",
        "alice",
        FinalApprovalBody(expected_revision=cast(str, page2.revision_id)),
    )
    approved_id = cast(str, approved.revision_id)
    assert approved.status == "APPROVED"
    revision = cast(object, approved.revision)
    assert approved.revision is not None and approved.revision.exports is not None
    exported_json = objects.read(approved.revision.exports.json_artifact)
    assert json.loads(exported_json)["document"]["pages"][1]["elements"][0]["text"] == (
        "page two corrected"
    )
    assert "data-review-html-version" not in exported_json.decode()
    html_export = objects.read(approved.revision.exports.html_artifact)
    html_text = html_export.decode()
    assert "<script" not in html_text
    assert "Tolerance ±0.1<br>Line two" in html_text
    assert approved.revision is not None
    assert f'data-job-id="{approved.revision.job_id}"' in html_text
    assert f'data-review-revision-id="{approved.revision.revision_id}"' in html_text
    assert f'data-review-generation="{approved.revision.generation}"' in html_text
    assert 'data-review-html-version="1"' in html_text
    assert 'data-conversion-status="SUCCEEDED"' in html_text
    page_two_node = next(node for node in approved.catalogue.nodes if node.page_number == 2)
    assert f'data-node-id="{page_two_node.node_id}"' in html_text
    assert "page two corrected" in html_text

    page_one_node = next(node for node in approved.catalogue.nodes if node.page_number == 1)
    reopened = service.update(
        "job",
        "alice",
        UpdateReviewBody(
            expected_revision=approved_id,
            changes=(RequestedChange(node_id=page_one_node.node_id, text="edited again"),),
        ),
    )
    assert reopened.status == "IN_REVIEW"
    approvals = {page.page_number: page.approval for page in reopened.pages}
    assert approvals[1] is None and approvals[2] is not None
    assert service.export("job", "alice", approved_id, "json").startswith("https://")
    assert objects.read(approved.revision.exports.html_artifact) == html_export
    assert objects.read(approved.revision.exports.json_artifact) == exported_json
    assert approved.revision.parent is not None
    assert revision is not None


def test_object_failure_and_failed_approval_publish_leave_old_head_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, heads, objects = make_service(warnings=False)

    def fail_revision(*args: object, **kwargs: object) -> Artifact:
        raise RuntimeError("object write failed")

    monkeypatch.setattr(objects, "put_revision", fail_revision)
    with pytest.raises(RuntimeError, match="object write failed"):
        service.update("job", "alice", UpdateReviewBody(expected_revision=None))
    assert heads.head is None

    monkeypatch.undo()
    service, heads, _ = make_service(warnings=False)
    saved = service.update("job", "alice", UpdateReviewBody(expected_revision=None))
    page_one = service.approve_page(
        "job",
        "alice",
        1,
        PageApprovalBody(expected_revision=cast(str, saved.revision_id)),
    )
    page_two = service.approve_page(
        "job",
        "alice",
        2,
        PageApprovalBody(expected_revision=cast(str, page_one.revision_id)),
    )
    authoritative = heads.head
    assert authoritative is not None
    publish = heads.publish

    def reject_approved(head: ReviewHead, expected_revision: str | None) -> bool:
        return False if head.status == "APPROVED" else publish(head, expected_revision)

    monkeypatch.setattr(heads, "publish", reject_approved)
    with pytest.raises(ReviewError, match="REVIEW_CONFLICT"):
        service.approve(
            "job",
            "alice",
            FinalApprovalBody(expected_revision=cast(str, page_two.revision_id)),
        )
    assert heads.head == authoritative
    with pytest.raises(ReviewError, match="EXPORT_NOT_FOUND"):
        service.export("job", "alice", IDS[3], "json")


def test_zero_findings_stays_in_review_and_incomplete_evidence_cannot_approve() -> None:
    service, _, objects = make_service(warnings=False)
    saved = service.update("job", "alice", UpdateReviewBody(expected_revision=None))
    assert saved.status == "IN_REVIEW" and saved.findings == ()
    assert saved.revision_id is not None
    first = service.approve_page(
        "job", "alice", 1, PageApprovalBody(expected_revision=saved.revision_id)
    )
    second = service.approve_page(
        "job", "alice", 2, PageApprovalBody(expected_revision=cast(str, first.revision_id))
    )
    assert second.status == "IN_REVIEW"
    objects.data[(RAW.key, RAW.version)] = b'{"Blocks":[{"Id":"p1","Page":1}]}'
    with pytest.raises(ReviewError, match="REVIEW_NOT_READY"):
        service.approve(
            "job",
            "alice",
            FinalApprovalBody(expected_revision=cast(str, second.revision_id)),
        )


def test_api_exact_routes_source_and_safe_validation() -> None:
    service, _, objects = make_service()
    app = FastAPI()
    app.state.document_review_service = service
    app.state.document_auth = Auth()
    app.include_router(router)
    install_errors(app)
    install_job_errors(app)
    client = TestClient(app)
    headers = {"Authorization": "Bearer alice"}
    path = "/api/v1/documents/jobs/job/review"
    assert client.get(path, headers=headers).json()["status"] == "NOT_REVIEWED"
    assert client.post(path, headers=headers).status_code == 405
    invalid = client.put(path, headers=headers, json={"changes": [{"node_id": "x", "text": "x"}]})
    assert invalid.status_code == 422 and invalid.json() == {"code": "INVALID_REVIEW"}
    source = client.get("/api/v1/documents/jobs/job/source", headers=headers)
    assert source.content == b"%PDF-synthetic"
    assert source.headers["cache-control"] == "no-store"
    assert source.headers["content-disposition"] == 'inline; filename="record.pdf"'
    assert objects.source_reads == 1


def test_reviewed_html_uses_canonical_heading_kinds() -> None:
    document = Document(
        source=Source(
            identity="s3://records-bucket/documents/incoming/job/source.pdf",
            bucket=SOURCE.bucket,
            key=SOURCE.key,
            version=SOURCE.version,
        ),
        status="SUCCEEDED",
        pages=(
            Page(
                number=1,
                reading_order="textract_layout",
                elements=(
                    Element(kind="title", text="Document title", references=()),
                    Element(kind="section_heading", text="Section heading", references=()),
                    Element(kind="text", text="Ordinary paragraph", references=()),
                    Element(
                        kind="table",
                        text="Caption",
                        references=(),
                        titles=(Content(text="Table title", references=()),),
                    ),
                    Element(kind="TITLE", text="Catalogue title", references=()),
                ),
            ),
        ),
    )
    revision = ReviewRevision(
        job_id="job",
        owner="alice",
        revision_id=IDS[0],
        generation=1,
        created_at=datetime.fromtimestamp(1_700_000_000, UTC),
        actor="alice",
        baseline=BASELINE,
        accepted_source=SOURCE,
        raw=RAW,
        document=document,
        catalogue=build_catalogue(document, BASELINE),
        pages=(PageState(page_number=1, content_hash="page-hash"),),
        findings=(),
        action="DRAFT_SAVED",
    )
    html = render_reviewed_html(revision)
    assert re.search(r"<h2\b[^>]*>Document title</h2>", html)
    assert re.search(r"<h3\b[^>]*>Section heading</h3>", html)
    assert re.search(r"<p\b[^>]*>Ordinary paragraph</p>", html)
    assert html.count("<h2") == 2
    assert re.search(r"<p\b[^>]*>Catalogue title</p>", html)
    assert 'data-kind="TITLE"' in html


def test_api_applies_tolerance_replacement_once_and_rejects_duplicates() -> None:
    service, _, _objects = make_service()
    app = FastAPI()
    app.state.document_review_service = service
    app.state.document_auth = Auth()
    app.include_router(router)
    install_errors(app)
    install_job_errors(app)
    client = TestClient(app)
    headers = {"Authorization": "Bearer alice"}
    path = "/api/v1/documents/jobs/job/review"
    initial = client.get(path, headers=headers).json()
    finding = initial["findings"][0]
    suggestion = finding["suggested_replacement"]
    node_id = suggestion["node_id"]
    replacement = {
        "finding_id": finding["finding_id"],
        "action": "RESOLVED_AFTER_EDIT",
        "replacement": {"node_id": node_id, "text": suggestion["text"]},
        "expected_region_hash": finding["region_hash"],
    }
    duplicate = client.put(
        path,
        headers=headers,
        json={
            "expected_revision": None,
            "changes": [{"node_id": node_id, "text": suggestion["text"]}],
            "decisions": [replacement],
        },
    )
    assert duplicate.status_code == 422 and duplicate.json() == {"code": "INVALID_REVIEW"}
    stale = client.put(
        path,
        headers=headers,
        json={
            "expected_revision": None,
            "changes": [],
            "decisions": [{**replacement, "expected_region_hash": "stale-hash"}],
        },
    )
    assert stale.status_code == 422 and stale.json() == {"code": "INVALID_REVIEW"}
    saved = client.put(
        path,
        headers=headers,
        json={"expected_revision": None, "changes": [], "decisions": [replacement]},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["document"]["pages"][0]["elements"][0]["text"] == "Tolerance ±0.1\nLine two"
    assert body["findings"][0]["decision"]["action"] == "RESOLVED_AFTER_EDIT"
    revision = service.get("job", "alice").revision
    assert revision is not None
    html = render_reviewed_html(revision)
    assert "Tolerance ±0.1<br>Line two" in html
    assert json.loads(revision.model_dump_json())["document"]["pages"][0]["elements"][0][
        "text"
    ] == ("Tolerance ±0.1\nLine two")


def test_api_applies_server_suggestion_for_toler_abbreviation() -> None:
    source = synthetic_document()
    element = source.pages[0].elements[0].model_copy(update={"text": "Toler +0.1%"})
    page = source.pages[0].model_copy(update={"elements": (element,)})
    document = source.model_copy(update={"pages": (page, *source.pages[1:])})
    service, _, _objects = make_service(document=document)
    app = FastAPI()
    app.state.document_review_service = service
    app.state.document_auth = Auth()
    app.include_router(router)
    install_errors(app)
    install_job_errors(app)
    client = TestClient(app)
    headers = {"Authorization": "Bearer alice"}
    path = "/api/v1/documents/jobs/job/review"
    initial = client.get(path, headers=headers).json()
    assert initial["document"]["pages"][0]["elements"][0]["text"] == "Toler +0.1%"
    finding = initial["findings"][0]
    suggestion = finding["suggested_replacement"]
    assert suggestion["text"] == "Tolerance ±0.1%"
    saved = client.put(
        path,
        headers=headers,
        json={
            "expected_revision": None,
            "changes": [],
            "decisions": [
                {
                    "finding_id": finding["finding_id"],
                    "action": "RESOLVED_AFTER_EDIT",
                    "replacement": {
                        "node_id": suggestion["node_id"],
                        "text": suggestion["text"],
                    },
                    "expected_region_hash": finding["region_hash"],
                }
            ],
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["document"]["pages"][0]["elements"][0]["text"] == "Tolerance ±0.1%"
    assert body["findings"][0]["decision"]["action"] == "RESOLVED_AFTER_EDIT"


def _review_client(service: ReviewService) -> TestClient:
    app = FastAPI()
    app.state.document_review_service = service
    app.state.document_auth = Auth()
    app.include_router(router)
    install_errors(app)
    install_job_errors(app)
    return TestClient(app)


def test_api_legacy_put_returns_top_level_review_state() -> None:
    service, _, _ = make_service()
    client = _review_client(service)
    headers = {"Authorization": "Bearer alice"}
    path = "/api/v1/documents/jobs/job/review"
    initial = client.get(path, headers=headers).json()
    node_id = next(
        node["node_id"] for node in initial["catalogue"]["nodes"] if node["page_number"] == 2
    )
    saved = client.put(
        path,
        headers=headers,
        json={
            "expected_revision": None,
            "changes": [{"node_id": node_id, "text": "page two corrected"}],
            "decisions": [],
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert "receipt" not in body
    parsed = ReviewState.model_validate(body)
    assert parsed.status == "IN_REVIEW"
    for field in (
        "document",
        "catalogue",
        "pages",
        "findings",
        "revision_id",
        "generation",
        "status",
        "revision",
    ):
        assert field in body
    assert parsed.revision_id is not None
    null_id = client.put(
        path,
        headers=headers,
        json={
            "expected_revision": parsed.revision_id,
            "changes": [{"node_id": node_id, "text": "second"}],
            "decisions": [],
            "operation_id": None,
        },
    )
    assert null_id.status_code == 200
    assert ReviewState.model_validate(null_id.json()).generation == 2
    malformed = client.put(
        path,
        headers=headers,
        json={"changes": [{"node_id": "x", "text": "x"}], "operation_id": "not-a-uuid"},
    )
    assert malformed.status_code == 422 and malformed.json() == {"code": "INVALID_REVIEW"}
    stale = client.put(
        path,
        headers=headers,
        json={"expected_revision": None, "changes": [], "decisions": []},
    )
    assert stale.status_code == 409 and stale.json() == {"code": "REVIEW_CONFLICT"}


def test_api_operation_aware_put_replays_current_review_state() -> None:
    service, _, _ = make_service()
    client = _review_client(service)
    headers = {"Authorization": "Bearer alice"}
    path = "/api/v1/documents/jobs/job/review"
    initial = client.get(path, headers=headers).json()
    node_id = next(
        node["node_id"] for node in initial["catalogue"]["nodes"] if node["page_number"] == 2
    )
    operation_a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    operation_b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    first = client.put(
        path,
        headers=headers,
        json={
            "expected_revision": None,
            "changes": [{"node_id": node_id, "text": "page two corrected"}],
            "decisions": [],
            "operation_id": operation_a,
        },
    )
    assert first.status_code == 200
    first_body = ReviewState.model_validate(first.json())
    second = client.put(
        path,
        headers=headers,
        json={
            "expected_revision": first_body.revision_id,
            "changes": [{"node_id": node_id, "text": "later edit"}],
            "decisions": [],
            "operation_id": operation_b,
        },
    )
    assert second.status_code == 200
    replay = client.put(
        path,
        headers=headers,
        json={
            "expected_revision": None,
            "changes": [{"node_id": node_id, "text": "page two corrected"}],
            "decisions": [],
            "operation_id": operation_a,
        },
    )
    assert replay.status_code == 200
    body = replay.json()
    assert "receipt" not in body
    parsed = ReviewState.model_validate(body)
    assert parsed.revision_id == ReviewState.model_validate(second.json()).revision_id
    assert parsed.document.pages[1].elements[0].text == "later edit"
    assert parsed.generation == 2


def test_api_unauthorized_does_not_expose_operation() -> None:
    service, heads, _ = make_service()
    client = _review_client(service)
    path = "/api/v1/documents/jobs/job/review"
    operation = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    payload: dict[str, object] = {
        "expected_revision": None,
        "changes": [],
        "decisions": [],
        "operation_id": operation,
    }
    original_get = heads.get
    calls = {"count": 0}

    def counting_get(job_id: str) -> ReviewHead | None:
        calls["count"] += 1
        return original_get(job_id)

    heads.get = counting_get  # type: ignore[method-assign]
    assert client.put(path, json=payload).status_code == 401
    assert (
        client.put(path, headers={"Authorization": "Bearer bob"}, json=payload).status_code == 401
    )
    assert calls["count"] == 0


def test_api_context_lookup_and_optional_header_compat() -> None:
    service, _, objects = make_service(storage_namespace="store-a")
    client = _review_client(service)
    headers = {"Authorization": "Bearer alice"}
    context_path = "/api/v1/documents/jobs/job/review/context"
    review_path = "/api/v1/documents/jobs/job/review"
    unavailable, _, _ = make_service()
    missing = _review_client(unavailable).get(context_path, headers=headers)
    assert missing.status_code == 503
    assert missing.json() == {"code": "REVIEW_CONTEXT_UNAVAILABLE"}
    assert client.get(context_path).status_code == 401
    response = client.get(context_path, headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["schema_version"] == 1
    assert body["job_id"] == "job"
    assert body["actor"] == "alice"
    assert body["baseline"]["key"] == BASELINE.key
    assert "receipt" not in body
    context_id = body["context_id"]
    assert len(context_id) == 64
    writes = list(objects.writes)
    mismatched = client.put(
        review_path,
        headers={**headers, "X-Review-Context": "b" * 64},
        json={"expected_revision": None, "changes": [], "decisions": []},
    )
    assert mismatched.status_code == 409
    assert mismatched.json() == {"code": "REVIEW_CONTEXT_CHANGED"}
    assert objects.writes == writes
    operation = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    lookup_path = f"{review_path}/operations/{operation}"
    assert client.get(lookup_path, headers=headers).status_code == 422
    looked = client.get(lookup_path, headers={**headers, "X-Review-Context": context_id})
    assert looked.status_code == 200
    payload = looked.json()
    assert payload["context"]["context_id"] == context_id
    assert payload["reconciliation"]["status"] == "UNRESOLVED"
    assert payload["reconciliation"]["receipt"] is None
    assert objects.writes == writes
    initial = client.get(review_path, headers=headers).json()
    node_id = next(
        node["node_id"] for node in initial["catalogue"]["nodes"] if node["page_number"] == 2
    )
    saved = client.put(
        review_path,
        headers={**headers, "X-Review-Context": context_id},
        json={
            "expected_revision": None,
            "changes": [{"node_id": node_id, "text": "page two corrected"}],
            "decisions": [],
            "operation_id": operation,
        },
    )
    assert saved.status_code == 200
    parsed = ReviewState.model_validate(saved.json())
    assert "receipt" not in saved.json()
    assert parsed.status == "IN_REVIEW"
    committed = client.get(lookup_path, headers={**headers, "X-Review-Context": context_id})
    assert committed.json()["reconciliation"]["status"] == "COMMITTED"
    assert committed.json()["reconciliation"]["receipt"]["revision_id"] == parsed.revision_id
    malformed = client.get(
        f"{review_path}/operations/not-a-uuid",
        headers={**headers, "X-Review-Context": context_id},
    )
    assert malformed.status_code == 422
    other = client.get(
        "/api/v1/documents/jobs/missing/review/context",
        headers=headers,
    )
    assert other.status_code == 404


def test_api_lookup_unauthorized_does_not_read_history() -> None:
    service, heads, _ = make_service(storage_namespace="store-a")
    client = _review_client(service)
    calls = {"count": 0}
    original_get = heads.get

    def counting_get(job_id: str) -> ReviewHead | None:
        calls["count"] += 1
        return original_get(job_id)

    heads.get = counting_get  # type: ignore[method-assign]
    path = "/api/v1/documents/jobs/job/review/operations/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert client.get(path).status_code == 401
    assert (
        client.get(
            path,
            headers={"Authorization": "Bearer bob", "X-Review-Context": "a" * 64},
        ).status_code
        == 401
    )
    assert calls["count"] == 0

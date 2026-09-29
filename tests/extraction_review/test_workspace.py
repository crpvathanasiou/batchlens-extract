"""Stage 3 extraction-review workspace API: open, page evidence, save, and approval."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Route

from app.api.extraction_reviews import mount_extraction_review
from app.extraction_review.contracts import (
    MAX_CANDIDATE_REFS_PER_FINDING,
    ExtractionReviewAction,
    ExtractionReviewState,
    LexicalFindingOrigin,
    PublishedManifestReference,
)
from app.extraction_review.local_jobs import LocalJobPhase, LocalJobStatus, LocalLexicalJob
from app.extraction_review.store import (
    REVIEWS_DIR_NAME,
    ExtractionReviewStore,
    derive_workspace_key,
)
from app.extraction_review.workspace import LOCAL_REVIEW_ACTOR, ExtractionReviewWorkspace
from app.lexical_extraction.contracts import (
    RECORD_SCHEMA_VERSION,
    BlockEvidence,
    BlockRecord,
    CategoricalExpression,
    CharSpan,
    Component,
    ComponentResult,
    DictionaryOccurrence,
    EquipmentTypeCandidate,
    ExactEvidence,
    ExtractionOutcome,
    ExtractionOutcomeRecord,
    FdaEmaMaterialCandidate,
    FinalManifestClaim,
    KnowledgeSnapshotIdentity,
    LexicalOccurrence,
    PageCoverage,
    PageEvidence,
    Preset,
    PublicationRecord,
    PublicationStatus,
    RunProvenance,
    UnitMention,
    UnitOccurrence,
    UnitOperationCandidate,
    ValueOccurrence,
)
from app.lexical_extraction.html_reader import open_reviewed_html
from app.lexical_extraction.publication import (
    COMPONENT_ARTIFACT_SCHEMA_VERSION,
    RUN_MANIFEST_SCHEMA_VERSION,
)
from tests.extraction_review.local_harness import create_app

LOCAL_JOB_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
FAILED_JOB_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
JOB_ID = "job-1"
REVISION_ID = "rev-doc-1"
RUN_ID = "run-1"
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
PAGE_1_A = "Add water to the tank."
PAGE_1_B = "Charge 2.5 kg then OFF."
PAGE_2 = "Begin mixing the batch."


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _span(text: str, literal: str) -> CharSpan:
    start = text.index(literal)
    return CharSpan(start_char=start, end_char=start + len(literal), matched_text=literal)


def _html() -> str:
    def page(number: int, body: str) -> str:
        return (
            f'<section class="page" id="source-page-{number}" data-page="{number}">'
            f'<h2 data-generated="true">Page {number}</h2>{body}</section>'
        )

    def paragraph(node_id: str, text: str) -> str:
        return (
            f'<article class="element" data-kind="text" data-element-id="{node_id}">'
            f'<p data-node-id="{node_id}">{text}</p></article>'
        )

    body = page(
        1,
        paragraph("n1", PAGE_1_A) + paragraph("n2", PAGE_1_B),
    ) + page(2, paragraph("n3", PAGE_2))
    return (
        "<!doctype html>"
        f'<html data-review-html-version="1" data-job-id="{JOB_ID}" '
        f'data-review-revision-id="{REVISION_ID}" data-review-generation="1" '
        'data-conversion-status="SUCCEEDED">'
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body>'
        '<header class="summary" data-generated="true"><h1>Reviewed document</h1></header>'
        f"<main>{body}</main></body></html>"
    )


def _block(
    node_id: str,
    text: str,
    page_number: int,
    order: int,
    *occurrences: LexicalOccurrence,
) -> BlockRecord:
    return BlockRecord(
        block=BlockEvidence(
            node_id=node_id,
            kind="text",
            text=text,
            page_number=page_number,
            order=order,
        ),
        occurrences=occurrences,
    )


def _page(number: int, order: int, *blocks: BlockRecord) -> dict[str, object]:
    page = PageEvidence(page_number=number, order=order, coverage=PageCoverage.COMPLETE)
    return {
        "page": page.model_dump(mode="json"),
        "blocks": [block.model_dump(mode="json") for block in blocks],
    }


def _write_artifact(path: Path, component: Component, pages: list[dict[str, object]]) -> None:
    payload = {
        "schema_version": COMPONENT_ARTIFACT_SCHEMA_VERSION,
        "record_schema_version": RECORD_SCHEMA_VERSION,
        "run_id": RUN_ID,
        "component": component.value,
        "page_count": len(pages),
        "pages": pages,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _occurrences() -> dict[Component, list[dict[str, object]]]:
    water = DictionaryOccurrence(
        occurrence_id="occ-water",
        block_node_id="n1",
        location=_span(PAGE_1_A, "water"),
        applies_to=(Component.MATERIALS,),
        candidates=(
            FdaEmaMaterialCandidate(
                matched_term="water",
                snapshot_id="snap-1",
                row_id="row-water",
                evidence=ExactEvidence(),
                source_field="material_name",
            ),
        ),
    )
    tank = DictionaryOccurrence(
        occurrence_id="occ-tank",
        block_node_id="n1",
        location=_span(PAGE_1_A, "tank"),
        applies_to=(Component.EQUIPMENT,),
        candidates=(
            EquipmentTypeCandidate(
                matched_term="tank",
                snapshot_id="snap-1",
                row_id="row-tank",
                evidence=ExactEvidence(),
            ),
        ),
    )
    unit = UnitOccurrence(
        occurrence_id="occ-kg",
        block_node_id="n2",
        mention=UnitMention(
            literal_text="kg",
            span=_span(PAGE_1_B, "kg"),
            evidence=ExactEvidence(),
        ),
    )
    value = ValueOccurrence(
        occurrence_id="occ-off",
        block_node_id="n2",
        expression=CategoricalExpression(
            raw_expression="OFF",
            span=_span(PAGE_1_B, "OFF"),
            category_label="OFF",
        ),
        applies_to=(Component.QUANTITY_EXPRESSIONS,),
    )
    mixing = DictionaryOccurrence(
        occurrence_id="occ-mixing",
        block_node_id="n3",
        location=_span(PAGE_2, "mixing"),
        applies_to=(Component.UNIT_OPERATIONS,),
        candidates=(
            UnitOperationCandidate(
                matched_term="mixing",
                snapshot_id="snap-1",
                row_id="row-mixing",
                evidence=ExactEvidence(),
            ),
        ),
    )
    return {
        Component.MATERIALS: [_page(1, 0, _block("n1", PAGE_1_A, 1, 0, water))],
        Component.EQUIPMENT: [_page(1, 0, _block("n1", PAGE_1_A, 1, 0, tank))],
        Component.UNITS: [_page(1, 0, _block("n2", PAGE_1_B, 1, 1, unit))],
        Component.QUANTITY_EXPRESSIONS: [_page(1, 0, _block("n2", PAGE_1_B, 1, 1, value))],
        Component.UNIT_OPERATIONS: [_page(2, 1, _block("n3", PAGE_2, 2, 0, mixing))],
    }


def _build(tmp_path: Path) -> tuple[Path, Path]:
    approved = tmp_path / "approved"
    html_path = approved / JOB_ID / REVISION_ID / "document.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text(_html(), encoding="utf-8")
    reader = open_reviewed_html(html_path)
    reader.read_all_pages()
    reviewed = reader.validated_input

    data = tmp_path / "data"
    run_dir = data / "extraction-raw-runs" / RUN_ID
    artifacts: list[dict[str, object]] = []
    for component, pages in _occurrences().items():
        relative = f"artifacts/component-{component.value}.json"
        path = run_dir / relative
        _write_artifact(path, component, pages)
        artifacts.append(
            {
                "component": component.value,
                "relative_path": relative,
                "byte_size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    resolved = (
        Component.UNIT_OPERATIONS,
        Component.MATERIALS,
        Component.EQUIPMENT,
        Component.UNITS,
        Component.QUANTITY_EXPRESSIONS,
    )
    extraction = ExtractionOutcomeRecord(
        overall=ExtractionOutcome.COMPLETED,
        components=tuple(
            ComponentResult(component=component, outcome=ExtractionOutcome.COMPLETED, match_count=1)
            for component in resolved
        ),
    )
    provenance = RunProvenance(
        run_id=RUN_ID,
        requested_presets=(Preset.FULL,),
        requested_components=resolved,
        resolved_components=resolved,
        fuzzy_requested=False,
        input_html_sha256=reviewed.html_sha256,
        knowledge=KnowledgeSnapshotIdentity(
            snapshot_id="snap-1",
            database_sha256="5" * 64,
            manifest_sha256="6" * 64,
        ),
        configuration_sha256="7" * 64,
        rules_sha256="8" * 64,
        engine_version="test",
    )
    publication = PublicationRecord(
        status=PublicationStatus.COMPLETED,
        final_manifest=FinalManifestClaim(manifest_id="manifest-run-1"),
    )
    manifest = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "manifest_id": "manifest-run-1",
        "run_id": RUN_ID,
        "publication": publication.model_dump(mode="json"),
        "artifacts": artifacts,
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    job = LocalLexicalJob(
        local_job_id=LOCAL_JOB_ID,
        job_id=JOB_ID,
        review_revision_id=REVISION_ID,
        action=ExtractionReviewAction.EXTRACT_ALL,
        fuzzy_enabled=False,
        status=LocalJobStatus.COMPLETED,
        phase=LocalJobPhase.COMPLETED,
        submitted_at=NOW,
        started_at=NOW,
        finished_at=NOW,
        reviewed_html=reviewed,
        run=provenance,
        extraction=extraction,
        publication=publication,
        raw_run_relative_dir=RUN_ID,
        published_manifest=PublishedManifestReference(
            manifest_id="manifest-run-1",
            manifest_sha256=_sha256(manifest_path),
        ),
    )
    failed = LocalLexicalJob(
        local_job_id=FAILED_JOB_ID,
        job_id="job-failed",
        review_revision_id=REVISION_ID,
        action=ExtractionReviewAction.EXTRACT_MATERIALS,
        status=LocalJobStatus.FAILED,
        phase=LocalJobPhase.FAILED,
        submitted_at=NOW,
        finished_at=NOW,
    )
    jobs = data / "extraction-jobs"
    jobs.mkdir(parents=True)
    (jobs / f"{LOCAL_JOB_ID}.json").write_text(job.model_dump_json(indent=2), encoding="utf-8")
    (jobs / f"{FAILED_JOB_ID}.json").write_text(failed.model_dump_json(indent=2), encoding="utf-8")
    return data, approved


def _app(tmp_path: Path) -> FastAPI:
    data, approved = _build(tmp_path)
    app = FastAPI()
    mount_extraction_review(app, ExtractionReviewWorkspace(data, approved))
    return app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(_app(tmp_path))


def _finding(payload: object, text: str) -> dict[str, object]:
    assert isinstance(payload, dict)
    body = cast(dict[str, object], payload)
    findings = cast(list[object], body["findings"])
    for item in findings:
        record = cast(dict[str, object], item)
        if record.get("original_matched_text") == text:
            return record
    raise AssertionError(text)


def _origin(state: ExtractionReviewState, text: str) -> LexicalFindingOrigin:
    for finding in state.findings:
        origin = finding.origin
        if isinstance(origin, LexicalFindingOrigin) and origin.original_matched_text == text:
            return origin
    raise AssertionError(text)


def test_list_open_initializes_one_current_review_and_reloads_it(tmp_path: Path) -> None:
    client = _client(tmp_path)
    listed = client.get("/api/v1/extraction-reviews/jobs")
    assert listed.status_code == 200
    jobs = listed.json()["jobs"]
    assert [job["local_job_id"] for job in jobs] == [LOCAL_JOB_ID]
    assert jobs[0]["job_id"] == JOB_ID
    assert jobs[0]["extraction_overall"] == "completed"

    opened = client.get(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}")
    assert opened.status_code == 200
    body = opened.json()
    assert body["approval_state"] == "not_approved"
    assert body["pages"] == [1, 2]
    assert body["current_revision_id"]
    water = _finding(body, "water")
    mixing = _finding(body, "mixing")
    assert water["page_number"] == 1
    assert water["block_node_id"] == "n1"
    assert water["display_text"] == "water"
    assert mixing["page_number"] == 2
    assert mixing["block_node_id"] == "n3"
    assert {item["original_matched_text"] for item in body["findings"]} == {
        "water",
        "tank",
        "kg",
        "OFF",
        "mixing",
    }

    data = tmp_path / "data"
    store = ExtractionReviewStore(data)
    state = store.load(JOB_ID)
    assert state.binding.document_source.document_hash is None
    water_origin = _origin(state, "water")
    assert water_origin.evidence.candidate_refs == ()
    assert water_origin.evidence.occurrence_kind == "dictionary"
    assert water_origin.evidence.occurrence_id == "occ-water"
    assert water_origin.evidence.block_node_id == "n1"
    assert water_origin.evidence.page_number == 1
    assert water_origin.evidence.location is not None
    assert water_origin.evidence.location.matched_text == "water"
    unit_origin = _origin(state, "kg")
    assert unit_origin.evidence.occurrence_kind == "unit"
    assert unit_origin.evidence.candidate_refs == ()
    value_origin = _origin(state, "OFF")
    assert value_origin.evidence.occurrence_kind == "value"
    assert value_origin.evidence.candidate_refs == ()

    stored = store.current_path(JOB_ID).read_bytes()
    again = client.get(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}")
    assert again.status_code == 200
    assert again.json()["current_revision_id"] == body["current_revision_id"]
    assert store.current_path(JOB_ID).read_bytes() == stored

    first_ids = {item["finding_id"] for item in body["findings"]}
    store.current_path(JOB_ID).unlink()
    rebuilt = client.get(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}")
    assert {item["finding_id"] for item in rebuilt.json()["findings"]} == first_ids


def test_open_succeeds_when_occurrence_exceeds_candidate_ref_limit(tmp_path: Path) -> None:
    """Published L13 may carry more catalogue refs than U1 stores; open must still work."""
    approved = tmp_path / "approved"
    html_path = approved / JOB_ID / REVISION_ID / "document.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text(_html(), encoding="utf-8")
    reader = open_reviewed_html(html_path)
    reader.read_all_pages()
    reviewed = reader.validated_input

    overflow = MAX_CANDIDATE_REFS_PER_FINDING + 1
    candidates = tuple(
        FdaEmaMaterialCandidate(
            matched_term="water",
            snapshot_id="snap-1",
            row_id=f"row-water-{index}",
            evidence=ExactEvidence(),
            source_field="material_name",
        )
        for index in range(overflow)
    )
    water = DictionaryOccurrence(
        occurrence_id="occ-water-many-refs",
        block_node_id="n1",
        location=_span(PAGE_1_A, "water"),
        applies_to=(Component.MATERIALS,),
        candidates=candidates,
    )
    assert len(water.candidates) > MAX_CANDIDATE_REFS_PER_FINDING

    data = tmp_path / "data"
    run_dir = data / "extraction-raw-runs" / RUN_ID
    relative = "artifacts/component-materials.json"
    path = run_dir / relative
    _write_artifact(
        path,
        Component.MATERIALS,
        [_page(1, 0, _block("n1", PAGE_1_A, 1, 0, water))],
    )
    extraction = ExtractionOutcomeRecord(
        overall=ExtractionOutcome.COMPLETED,
        components=(
            ComponentResult(
                component=Component.MATERIALS,
                outcome=ExtractionOutcome.COMPLETED,
                match_count=1,
            ),
        ),
    )
    provenance = RunProvenance(
        run_id=RUN_ID,
        requested_presets=(Preset.MATERIALS_WITH_QUANTITIES,),
        requested_components=(Component.MATERIALS,),
        resolved_components=(Component.MATERIALS,),
        fuzzy_requested=False,
        input_html_sha256=reviewed.html_sha256,
        knowledge=KnowledgeSnapshotIdentity(
            snapshot_id="snap-1",
            database_sha256="5" * 64,
            manifest_sha256="6" * 64,
        ),
        configuration_sha256="7" * 64,
        rules_sha256="8" * 64,
        engine_version="test",
    )
    publication = PublicationRecord(
        status=PublicationStatus.COMPLETED,
        final_manifest=FinalManifestClaim(manifest_id="manifest-run-1"),
    )
    manifest_path = run_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
                "manifest_id": "manifest-run-1",
                "run_id": RUN_ID,
                "publication": publication.model_dump(mode="json"),
                "artifacts": [
                    {
                        "component": Component.MATERIALS.value,
                        "relative_path": relative,
                        "byte_size": path.stat().st_size,
                        "sha256": _sha256(path),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    job = LocalLexicalJob(
        local_job_id=LOCAL_JOB_ID,
        job_id=JOB_ID,
        review_revision_id=REVISION_ID,
        action=ExtractionReviewAction.EXTRACT_MATERIALS,
        fuzzy_enabled=False,
        status=LocalJobStatus.COMPLETED,
        phase=LocalJobPhase.COMPLETED,
        submitted_at=NOW,
        started_at=NOW,
        finished_at=NOW,
        reviewed_html=reviewed,
        run=provenance,
        extraction=extraction,
        publication=publication,
        raw_run_relative_dir=RUN_ID,
        published_manifest=PublishedManifestReference(
            manifest_id="manifest-run-1",
            manifest_sha256=_sha256(manifest_path),
        ),
    )
    jobs = data / "extraction-jobs"
    jobs.mkdir(parents=True)
    (jobs / f"{LOCAL_JOB_ID}.json").write_text(job.model_dump_json(indent=2), encoding="utf-8")

    app = FastAPI()
    mount_extraction_review(app, ExtractionReviewWorkspace(data, approved))
    client = TestClient(app)
    opened = client.get(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}")
    assert opened.status_code == 200
    body = opened.json()
    water_finding = _finding(body, "water")
    assert water_finding["page_number"] == 1
    assert water_finding["block_node_id"] == "n1"
    assert water_finding["display_text"] == "water"
    assert water_finding["original_matched_text"] == "water"
    assert water_finding["start_char"] is not None
    assert water_finding["end_char"] is not None

    state = ExtractionReviewStore(data).load(JOB_ID)
    origin = _origin(state, "water")
    assert origin.evidence.candidate_refs == ()
    assert origin.evidence.occurrence_id == "occ-water-many-refs"
    assert origin.evidence.occurrence_kind == "dictionary"
    assert origin.evidence.block_node_id == "n1"
    assert origin.evidence.page_number == 1
    assert origin.evidence.location is not None
    assert origin.evidence.location.matched_text == "water"
    assert origin.evidence.location.start_char == water_finding["start_char"]
    assert origin.evidence.location.end_char == water_finding["end_char"]


def test_page_html_uses_source_spans_and_does_not_invent_user_evidence(tmp_path: Path) -> None:
    client = _client(tmp_path)
    opened = client.get(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}").json()
    water = _finding(opened, "water")
    page = client.get(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}/pages/1")
    assert page.status_code == 200
    html = page.json()["html"]
    assert page.json()["page_number"] == 1
    assert 'data-node-id="n1"' in html
    assert f'data-finding-id="{water["finding_id"]}"' in html
    assert ">water</mark>" in html
    assert "bl-hit--material" in html
    assert "bl-hit--equipment" in html
    assert "bl-hit--other" in html
    other = client.get(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}/pages/2")
    other_html = other.json()["html"]
    assert ">mixing</mark>" in other_html
    assert "bl-hit--unit-operation" in other_html
    assert "water" not in other_html
    missing = client.get(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}/pages/9")
    assert missing.status_code == 404


def test_page_scoped_save_persists_and_later_save_clears_approval(tmp_path: Path) -> None:
    client = _client(tmp_path)
    opened = client.get(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}").json()
    revision = opened["current_revision_id"]
    water = _finding(opened, "water")
    tank = _finding(opened, "tank")
    saved = client.put(
        f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}",
        json={
            "expected_revision_id": revision,
            "edits": [
                {
                    "op": "patch_text",
                    "finding_id": water["finding_id"],
                    "page_number": 1,
                    "display_text": "purified water",
                },
                {
                    "op": "remove",
                    "finding_id": tank["finding_id"],
                    "page_number": 1,
                },
                {
                    "op": "add",
                    "finding_id": "added-note",
                    "page_number": 1,
                    "component": "materials",
                    "display_text": "operator note",
                },
            ],
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["approval_state"] == "not_approved"
    assert body["current_revision_id"] != revision
    edited = _finding(body, "water")
    assert edited["display_text"] == "purified water"
    assert edited["original_matched_text"] == "water"
    assert edited["changed_by_user"] is True
    removed = _finding(body, "tank")
    assert removed["removed"] is True
    assert removed["removed_by_user"] is True
    added = next(item for item in body["findings"] if item["finding_id"] == "added-note")
    assert added["origin_kind"] == "user_added"
    assert added["evidence_status"] == "no_document_evidence"
    assert added["page_number"] == 1
    assert added["block_node_id"] is None
    assert added["added_by_user"] is True

    page = client.get(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}/pages/1").json()["html"]
    assert "added-note" not in page
    assert ">water</mark>" in page

    wrong_page = client.put(
        f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}",
        json={
            "expected_revision_id": body["current_revision_id"],
            "edits": [
                {
                    "op": "patch_text",
                    "finding_id": _finding(body, "mixing")["finding_id"],
                    "page_number": 1,
                    "display_text": "not this page",
                }
            ],
        },
    )
    assert wrong_page.status_code == 422

    stale = client.put(
        f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}",
        json={
            "expected_revision_id": revision,
            "edits": [
                {
                    "op": "patch_text",
                    "finding_id": water["finding_id"],
                    "page_number": 1,
                    "display_text": "stale",
                }
            ],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "REVIEW_CONFLICT"

    reloaded = client.get(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}").json()
    assert reloaded["current_revision_id"] == body["current_revision_id"]
    assert _finding(reloaded, "water")["display_text"] == "purified water"

    rejected = client.post(
        f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}/approve",
        json={"expected_revision_id": revision, "findings": [{"display_text": "unsaved"}]},
    )
    assert rejected.status_code == 422

    conflict = client.post(
        f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}/approve",
        json={"expected_revision_id": revision},
    )
    assert conflict.status_code == 409

    approved = client.post(
        f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}/approve",
        json={"expected_revision_id": body["current_revision_id"]},
    )
    assert approved.status_code == 200
    assert approved.json()["approval_state"] == "approved"
    assert approved.json()["current_revision_id"] == body["current_revision_id"]
    stored = ExtractionReviewStore(tmp_path / "data").load(JOB_ID)
    assert stored.approval is not None
    assert stored.approval.actor == LOCAL_REVIEW_ACTOR
    assert stored.approval.approved_revision_id == body["current_revision_id"]

    cleared = client.put(
        f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}",
        json={
            "expected_revision_id": body["current_revision_id"],
            "edits": [
                {
                    "op": "patch_text",
                    "finding_id": water["finding_id"],
                    "page_number": 1,
                    "display_text": "water again",
                }
            ],
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["approval_state"] == "not_approved"
    assert ExtractionReviewStore(tmp_path / "data").load(JOB_ID).approval is None


def test_no_page_or_finding_approval_and_no_revision_history(tmp_path: Path) -> None:
    app = _app(tmp_path)
    client = TestClient(app)
    client.get(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}")
    paths = {route.path for route in app.routes if isinstance(route, Route)}
    assert "/api/v1/extraction-reviews/jobs/{local_job_id}/approve" in paths
    assert not any("/pages/" in path and path.endswith("/approve") for path in paths)
    assert not any("findings" in path and "approve" in path for path in paths)
    assert not any("revisions" in path for path in paths)

    missing_page = client.post(f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}/pages/1/approve")
    missing_finding = client.post(
        f"/api/v1/extraction-reviews/jobs/{LOCAL_JOB_ID}/findings/water/approve"
    )
    assert missing_page.status_code == 404
    assert missing_finding.status_code == 404

    review_root = tmp_path / "data" / REVIEWS_DIR_NAME
    files = sorted(path.name for path in review_root.rglob("*") if path.is_file())
    assert files == ["current-review.json"]
    assert not list((tmp_path / "data").rglob("*.sqlite"))
    assert not list((tmp_path / "data").rglob("history.jsonl"))
    key = derive_workspace_key(JOB_ID)
    assert (review_root / key / "current-review.json").is_file()


def test_harness_serves_the_extraction_review_screen(tmp_path: Path) -> None:
    data, approved = _build(tmp_path)
    static = tmp_path / "static"
    static.mkdir()
    (static / "review.js").write_text("export {}", encoding="utf-8")
    (static / "review.css").write_text(".bl-review{}", encoding="utf-8")
    app = create_app(data_dir=data, approved_documents_root=approved, static_dir=static)
    client = TestClient(app)
    page = client.get("/documents/local-extraction-review")
    assert page.status_code == 200
    assert 'id="extraction-review"' in page.text
    bootstrap = client.get("/documents/local-extraction-review/bootstrap.js")
    assert bootstrap.status_code == 200
    assert "mountExtractionReviewWorkspace" in bootstrap.text
    listed = client.get("/api/v1/extraction-reviews/jobs")
    assert listed.status_code == 200
    assert listed.json()["jobs"][0]["local_job_id"] == LOCAL_JOB_ID

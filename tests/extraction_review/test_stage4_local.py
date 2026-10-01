"""Local Stage 4 workspace API: classify, Extract All, and snapshot display."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.extraction_reviews import mount_extraction_review
from app.extraction_review.approved_documents import DOCUMENT_HTML_NAME
from app.extraction_review.local_jobs import (
    CLASSIFICATION_SNAPSHOT_FILENAME,
    JOBS_DIR_NAME,
    NO_ELIGIBLE_PAGES_MESSAGE,
    ClassifiedExtractionContext,
    LocalLexicalJob,
    LocalLexicalJobService,
)
from app.extraction_review.stage4_local import LocalStage4Adapter
from app.extraction_review.store import ExtractionReviewStore
from app.extraction_review.workspace import ExtractionReviewWorkspace
from app.lexical_extraction.configuration import EffectiveExecutionConfiguration
from app.lexical_extraction.contracts import (
    ComponentResult,
    ExtractionOutcome,
    ExtractionOutcomeRecord,
    FinalManifestClaim,
    KnowledgeSnapshotIdentity,
    PublicationRecord,
    PublicationStatus,
    RunProvenance,
    SafeStructuredError,
    Stage4PageRestrictionProvenance,
)
from app.lexical_extraction.monitoring import RunMonitoringAccumulator
from app.lexical_extraction.publication import FilesystemEvidenceSink, PublicationResult
from app.lexical_extraction.runner import LexicalRunResult
from app.page_classification.contracts import (
    ClassificationProgress,
    CompletedPageClassificationResult,
    CurrentClassificationState,
    EligibilityDecision,
    SourceEvidenceValidation,
    persist_call_outcome,
)
from app.page_classification.page_classification_schemas import (
    DocumentSupportingResponse,
    MaterialEquipmentResponse,
    ProcessOperationsResponse,
)
from app.page_classification.page_input import prepare_reviewed_document
from app.page_classification.rules import validate_call_response
from app.page_classification.service import PageClassificationBusyError
from app.page_classification.store import (
    PageClassificationStore,
    canonical_classification_snapshot_bytes,
    classification_snapshot_sha256,
)
from tests.extraction_review import test_workspace as workspace_fixtures
from tests.extraction_review.local_harness import create_app


def _workspace_build(tmp_path: Path) -> tuple[Path, Path]:
    return workspace_fixtures._build(tmp_path)  # type: ignore[reportPrivateUsage]


PC_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "page_classification"
    / "fixtures"
    / "reviewed_html_v1.html"
)
PC_JOB = "job-page-class-1"
PC_REV = "rev-page-class-1"
FIXED_NOW = datetime(2026, 10, 1, 14, 0, 0, tzinfo=UTC)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _wait_for(predicate: Any, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met before timeout")


def _write_config(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "input:",
                "  reviewed_html_path: ./placeholder.html",
                "knowledge:",
                "  snapshot_directory: ./snapshot",
                "output:",
                "  directory: ./output",
                "extraction:",
                "  presets: [materials_with_quantities]",
                "  components: []",
                "  fuzzy_enabled: false",
                "resources:",
                "  sqlite_read_batch_rows: 64",
                "  sqlite_cache_kib: 1024",
                "  max_terms_per_shard: 1000",
                "  max_term_codepoints_per_shard: 20000",
                "  result_buffer_records: 256",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (path.parent / "snapshot").mkdir(exist_ok=True)
    return path


def _empty_monitoring() -> Any:
    return RunMonitoringAccumulator().freeze()


def _classified_executor() -> Any:
    def execute(
        config: EffectiveExecutionConfiguration,
        sink: FilesystemEvidenceSink,
        page_allow_list: tuple[int, ...],
        stage4_page_restriction: Stage4PageRestrictionProvenance,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        del page_allow_list, stage4_page_restriction
        run_id = str(uuid.uuid4())
        sink.begin_run(run_id)
        sink.complete_run()
        assert sink.run_directory is not None
        html_sha = _sha256(config.input.reviewed_html_path.read_bytes())
        knowledge = KnowledgeSnapshotIdentity(
            snapshot_id="snap-test",
            database_sha256="5" * 64,
            manifest_sha256="6" * 64,
        )
        provenance = RunProvenance(
            run_id=run_id,
            requested_presets=config.extraction.presets,
            requested_components=config.extraction.components,
            resolved_components=config.resolved_components,
            fuzzy_requested=config.extraction.fuzzy_enabled,
            input_html_sha256=html_sha,
            knowledge=knowledge,
            configuration_sha256="7" * 64,
            rules_sha256="8" * 64,
            engine_version="test",
        )
        extraction = ExtractionOutcomeRecord(
            overall=ExtractionOutcome.COMPLETED,
            components=tuple(
                ComponentResult(
                    component=component,
                    outcome=ExtractionOutcome.COMPLETED,
                    match_count=1,
                )
                for component in config.resolved_components
            ),
        )
        run_result = LexicalRunResult(
            run_id=run_id,
            validated_input=None,
            knowledge=knowledge,
            provenance=provenance,
            extraction=extraction,
            pre_validation=None,
            monitoring=_empty_monitoring(),
        )
        manifest_path = sink.run_directory / "manifest.json"
        manifesto = {
            "schema_version": "batchlens.lexical-run-manifest.v1",
            "manifest_id": f"manifest-{run_id}",
        }
        manifest_path.write_text(json.dumps(manifesto), encoding="utf-8")
        return run_result, PublicationResult(
            run_id=run_id,
            run_directory=sink.run_directory,
            publication=PublicationRecord(
                status=PublicationStatus.COMPLETED,
                final_manifest=FinalManifestClaim(manifest_id=f"manifest-{run_id}"),
            ),
            manifest_path=manifest_path,
            artifacts=(),
            exit_code=0,
            error=None,
        )

    return execute


@pytest.fixture
def stage4_env(tmp_path: Path) -> dict[str, Any]:
    data_dir = tmp_path / "data"
    approved = tmp_path / "approved"
    data_dir.mkdir()
    approved.mkdir()
    config_path = _write_config(tmp_path / "config" / "execution.yaml")
    directory = approved / PC_JOB / PC_REV
    directory.mkdir(parents=True)
    (directory / DOCUMENT_HTML_NAME).write_bytes(PC_FIXTURE.read_bytes())
    document = prepare_reviewed_document(directory / DOCUMENT_HTML_NAME)
    return {
        "data_dir": data_dir,
        "approved": approved,
        "config_path": config_path,
        "document": document,
        "html_path": directory / DOCUMENT_HTML_NAME,
    }


class FakeClassificationService:
    def __init__(self, data_dir: Path) -> None:
        self._store = PageClassificationStore(data_dir)
        self.started: list[Path] = []
        self.busy = False
        self.next_state: CurrentClassificationState | None = None

    def get_current(self, reviewed_html: Any) -> CurrentClassificationState | None:
        return self._store.load(reviewed_html)

    def start_classification(
        self,
        reviewed_html_path: Path,
        *,
        expected: Any,
    ) -> CurrentClassificationState:
        if self.busy:
            raise PageClassificationBusyError("busy")
        self.started.append(reviewed_html_path)
        if self.next_state is not None:
            return self._store.save(self.next_state)
        now = FIXED_NOW
        prepared = prepare_reviewed_document(reviewed_html_path, expected=expected)
        state = CurrentClassificationState(
            reviewed_html=prepared.reviewed_html,
            status="running",
            created_at=now,
            updated_at=now,
            finished_at=None,
            progress=ClassificationProgress(
                total_pages=len(prepared.pages),
                completed_pages=0,
                current_page_number=prepared.pages[0].binding.page_number,
            ),
            page_results=(),
            terminal_reason=None,
        )
        return self._store.save(state)


def _empty_responses() -> tuple[Any, Any, Any]:
    empty: dict[str, object] = {"labels": [], "status": "empty", "evidence": []}
    return (
        MaterialEquipmentResponse.model_validate(empty),
        ProcessOperationsResponse.model_validate(empty),
        DocumentSupportingResponse.model_validate(empty),
    )


def _completed_page(
    document: Any,
    page_number: int,
    *,
    eligible: bool,
    kind: str = "empty",
    requires_review: bool = False,
) -> CompletedPageClassificationResult:
    page = next(item for item in document.pages if item.binding.page_number == page_number)
    binding = page.binding
    one, two, three = _empty_responses()
    outcomes = (
        persist_call_outcome(validate_call_response(binding, 1, one)),
        persist_call_outcome(validate_call_response(binding, 2, two)),
        persist_call_outcome(validate_call_response(binding, 3, three)),
    )
    source = SourceEvidenceValidation(
        binding=binding,
        items=(),
        has_unverified=False,
        requires_review=requires_review,
    )
    eligibility = EligibilityDecision(
        binding=binding,
        eligible_for_extraction=eligible,
        reason=(
            "every final label belongs to the fixed exclusion set"
            if not eligible
            else "page remains eligible for lexical extraction"
        ),
        excluded_by_policy=not eligible,
    )
    return CompletedPageClassificationResult(
        binding=binding,
        call_outcomes=outcomes,
        source_validation=source,
        kind=kind,  # type: ignore[arg-type]
        labels=(),
        response_statuses=("empty", "empty", "empty"),
        reasons=("all three valid responses have status empty",),
        requires_review=requires_review,
        is_provisional=False,
        applied_other_unclassified=False,
        eligibility=eligibility,
    )


def _save_classification(
    data_dir: Path,
    document: Any,
    *,
    status: str,
    page_results: tuple[CompletedPageClassificationResult, ...],
    terminal_reason: str | None = None,
) -> CurrentClassificationState:
    finished = FIXED_NOW if status != "running" else None
    current_page: int | None = None
    if status == "running" and len(page_results) < len(document.pages):
        current_page = document.pages[len(page_results)].binding.page_number
    state = CurrentClassificationState(
        reviewed_html=document.reviewed_html,
        status=status,  # type: ignore[arg-type]
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        finished_at=finished,
        progress=ClassificationProgress(
            total_pages=len(document.pages),
            completed_pages=len(page_results),
            current_page_number=current_page,
        ),
        page_results=page_results,
        terminal_reason=terminal_reason,
    )
    return PageClassificationStore(data_dir).save(state)


def _client(
    env: dict[str, Any],
    *,
    classification: FakeClassificationService | None = None,
    lexical: LocalLexicalJobService | None = None,
) -> tuple[TestClient, FakeClassificationService, LocalLexicalJobService]:
    fake = classification or FakeClassificationService(env["data_dir"])
    service = lexical or LocalLexicalJobService(
        env["data_dir"],
        execute_classified_stage2=_classified_executor(),
        clock=lambda: FIXED_NOW,
    )
    adapter = LocalStage4Adapter(
        env["data_dir"],
        env["approved"],
        classification_service=fake,
        lexical_job_service=service,
        config_path=env["config_path"],
    )
    app = FastAPI()
    mount_extraction_review(
        app,
        ExtractionReviewWorkspace(env["data_dir"], env["approved"]),
        stage4_adapter=adapter,
    )
    return TestClient(app), fake, service


def test_lists_approved_documents_and_exact_page_binding(stage4_env: dict[str, Any]) -> None:
    client, _fake, service = _client(stage4_env)
    try:
        listed = client.get("/api/v1/extraction-reviews/approved-documents")
        assert listed.status_code == 200
        documents = listed.json()["documents"]
        assert documents == [{"job_id": PC_JOB, "review_revision_id": PC_REV}]

        pages = client.get(f"/api/v1/extraction-reviews/approved-documents/{PC_JOB}/{PC_REV}/pages")
        assert pages.status_code == 200
        assert pages.json()["pages"] == [1, 2, 3]

        html = client.get(
            f"/api/v1/extraction-reviews/approved-documents/{PC_JOB}/{PC_REV}/pages/2"
        )
        assert html.status_code == 200
        body = html.json()
        assert body["page_number"] == 2
        assert 'data-page="2"' in body["html"]
        assert "Sodium Chloride" in body["html"]
    finally:
        service.close()


def test_classification_absent_running_completed_interrupted(stage4_env: dict[str, Any]) -> None:
    client, fake, service = _client(stage4_env)
    try:
        absent = client.get(
            f"/api/v1/extraction-reviews/approved-documents/{PC_JOB}/{PC_REV}/classification"
        )
        assert absent.status_code == 200
        assert absent.json()["classification"] is None

        document = stage4_env["document"]
        running = _save_classification(
            stage4_env["data_dir"],
            document,
            status="running",
            page_results=(_completed_page(document, 1, eligible=True),),
        )
        response = client.get(
            f"/api/v1/extraction-reviews/approved-documents/{PC_JOB}/{PC_REV}/classification"
        )
        assert response.status_code == 200
        payload = response.json()["classification"]
        assert payload["status"] == "running"
        assert payload["progress"]["completed_pages"] == 1
        assert payload["progress"]["current_page_number"] == 2
        assert payload["source"] == "current"

        completed = _save_classification(
            stage4_env["data_dir"],
            document,
            status="completed",
            page_results=(
                _completed_page(document, 1, eligible=False, kind="completed"),
                _completed_page(
                    document, 2, eligible=True, kind="needs_review", requires_review=True
                ),
                _completed_page(document, 3, eligible=True),
            ),
        )
        response = client.get(
            f"/api/v1/extraction-reviews/approved-documents/{PC_JOB}/{PC_REV}/classification"
        )
        page_two = next(
            item for item in response.json()["classification"]["pages"] if item["page_number"] == 2
        )
        assert page_two["requires_review"] is True
        assert page_two["eligibility"]["eligible_for_extraction"] is True
        assert response.json()["classification"]["status"] == "completed"
        assert completed.status == "completed"

        interrupted = _save_classification(
            stage4_env["data_dir"],
            document,
            status="interrupted",
            page_results=(_completed_page(document, 1, eligible=True),),
            terminal_reason="page classification was interrupted by service restart",
        )
        response = client.get(
            f"/api/v1/extraction-reviews/approved-documents/{PC_JOB}/{PC_REV}/classification"
        )
        assert response.json()["classification"]["status"] == "interrupted"
        assert "interrupted" in response.json()["classification"]["terminal_reason"]
        assert interrupted.status == "interrupted"
        assert running.status == "running"
        assert fake.get_current(document.reviewed_html) is not None
    finally:
        service.close()


def test_start_classification_uses_injected_fake_and_busy_error(
    stage4_env: dict[str, Any],
) -> None:
    fake = FakeClassificationService(stage4_env["data_dir"])
    client, _same, service = _client(stage4_env, classification=fake)
    try:
        started = client.post(
            f"/api/v1/extraction-reviews/approved-documents/{PC_JOB}/{PC_REV}/classify"
        )
        assert started.status_code == 200
        assert started.json()["classification"]["status"] == "running"
        assert fake.started == [stage4_env["html_path"].resolve()]

        fake.busy = True
        busy = client.post(
            f"/api/v1/extraction-reviews/approved-documents/{PC_JOB}/{PC_REV}/classify"
        )
        assert busy.status_code == 409
        assert busy.json()["code"] == "CLASSIFICATION_BUSY"
        assert "sk-" not in busy.json()["message"]
        assert "\\" not in busy.json()["message"]
    finally:
        service.close()


def test_classifier_unavailable_without_service(stage4_env: dict[str, Any]) -> None:
    adapter = LocalStage4Adapter(
        stage4_env["data_dir"],
        stage4_env["approved"],
        classification_service=None,
        lexical_job_service=None,
        config_path=None,
    )
    app = FastAPI()
    mount_extraction_review(
        app,
        ExtractionReviewWorkspace(stage4_env["data_dir"], stage4_env["approved"]),
        stage4_adapter=adapter,
    )
    client = TestClient(app)
    response = client.post(
        f"/api/v1/extraction-reviews/approved-documents/{PC_JOB}/{PC_REV}/classify"
    )
    assert response.status_code == 503
    assert response.json()["code"] == "CLASSIFIER_UNAVAILABLE"


def _threads_idle(service: LocalLexicalJobService) -> bool:
    threads = getattr(service, "_threads", [])
    return all(not thread.is_alive() for thread in list(threads))


def test_extract_all_submission_status_and_no_eligible(stage4_env: dict[str, Any]) -> None:
    document = stage4_env["document"]
    _save_classification(
        stage4_env["data_dir"],
        document,
        status="completed",
        page_results=(
            _completed_page(document, 1, eligible=True),
            _completed_page(document, 2, eligible=True, kind="needs_review", requires_review=True),
            _completed_page(document, 3, eligible=True),
        ),
    )
    client, _fake, service = _client(stage4_env)
    try:
        submitted = client.post(
            f"/api/v1/extraction-reviews/approved-documents/{PC_JOB}/{PC_REV}/extract-all"
        )
        assert submitted.status_code == 200
        payload = submitted.json()
        assert payload["kind"] == "submitted"
        local_job_id = payload["job"]["local_job_id"]
        assert payload["job"]["status"] == "queued"
        assert payload["job"]["classified"] is True

        status = client.get(f"/api/v1/extraction-reviews/local-jobs/{local_job_id}")
        assert status.status_code == 200
        assert status.json()["local_job_id"] == local_job_id

        _wait_for(lambda: service.get_job(local_job_id).status.value in {"completed", "failed"})
        terminal = client.get(f"/api/v1/extraction-reviews/local-jobs/{local_job_id}")
        body = terminal.json()
        assert body["status"] == "completed"
        assert body["extraction_overall"] == "completed"
        assert body["reviewable"] is True
    finally:
        _wait_for(lambda: _threads_idle(service), timeout=5.0)
        service.close()

    document = stage4_env["document"]
    before_jobs = {path.name for path in (stage4_env["data_dir"] / JOBS_DIR_NAME).glob("*.json")}
    _save_classification(
        stage4_env["data_dir"],
        document,
        status="completed",
        page_results=(
            _completed_page(document, 1, eligible=False, kind="completed"),
            _completed_page(document, 2, eligible=False, kind="completed"),
            _completed_page(document, 3, eligible=False, kind="completed"),
        ),
    )
    client2, _fake2, service2 = _client(stage4_env)
    try:
        none_eligible = client2.post(
            f"/api/v1/extraction-reviews/approved-documents/{PC_JOB}/{PC_REV}/extract-all"
        )
        assert none_eligible.status_code == 200
        body = none_eligible.json()
        assert body["kind"] == "no_eligible_pages"
        assert body["message"] == NO_ELIGIBLE_PAGES_MESSAGE
        after_jobs = {path.name for path in (stage4_env["data_dir"] / JOBS_DIR_NAME).glob("*.json")}
        assert after_jobs == before_jobs
    finally:
        service2.close()


def test_published_all_failed_job_status_is_not_reviewable(tmp_path: Path) -> None:
    data, approved = _workspace_build(tmp_path)
    local_job_id = workspace_fixtures.LOCAL_JOB_ID
    job_path = data / JOBS_DIR_NAME / f"{local_job_id}.json"
    job = LocalLexicalJob.model_validate_json(job_path.read_text(encoding="utf-8"))
    failed_extraction = ExtractionOutcomeRecord(
        overall=ExtractionOutcome.FAILED,
        components=tuple(
            ComponentResult(
                component=item.component,
                outcome=ExtractionOutcome.FAILED,
                error=SafeStructuredError(
                    code="SINK_WRITE_FAILED",
                    message="evidence sink page write failed: PublicationError",
                    component=item.component,
                    retryable=False,
                ),
            )
            for item in job.extraction.components  # type: ignore[union-attr]
        ),
    )
    mutated = job.model_copy(update={"extraction": failed_extraction})
    job_path.write_text(mutated.model_dump_json(indent=2), encoding="utf-8")

    service = LocalLexicalJobService(data)
    try:
        adapter = LocalStage4Adapter(
            data,
            approved,
            classification_service=FakeClassificationService(data),
            lexical_job_service=service,
            config_path=None,
        )
        app = FastAPI()
        mount_extraction_review(
            app,
            ExtractionReviewWorkspace(data, approved),
            stage4_adapter=adapter,
        )
        client = TestClient(app)

        listed = client.get("/api/v1/extraction-reviews/jobs")
        assert listed.status_code == 200
        assert listed.json() == {"jobs": []}

        status = client.get(f"/api/v1/extraction-reviews/local-jobs/{local_job_id}")
        assert status.status_code == 200
        payload = status.json()
        assert payload["status"] == "completed"
        assert payload["phase"] == "completed"
        assert payload["extraction_overall"] == "failed"
        assert payload["reviewable"] is False

        opened = client.get(f"/api/v1/extraction-reviews/jobs/{local_job_id}")
        assert opened.status_code == 409
        assert opened.json()["code"] == "JOB_NOT_REVIEWABLE"
    finally:
        service.close()


def test_classified_snapshot_used_not_later_current(stage4_env: dict[str, Any]) -> None:
    document = stage4_env["document"]
    original = _save_classification(
        stage4_env["data_dir"],
        document,
        status="completed",
        page_results=(
            _completed_page(document, 1, eligible=True),
            _completed_page(document, 2, eligible=True),
            _completed_page(document, 3, eligible=True),
        ),
    )
    client, _fake, service = _client(stage4_env)
    try:
        submitted = client.post(
            f"/api/v1/extraction-reviews/approved-documents/{PC_JOB}/{PC_REV}/extract-all"
        )
        local_job_id = submitted.json()["job"]["local_job_id"]
        original_digest = classification_snapshot_sha256(original)
        snapshot_path = (
            stage4_env["data_dir"] / JOBS_DIR_NAME / local_job_id / CLASSIFICATION_SNAPSHOT_FILENAME
        )
        assert snapshot_path.is_file()

        later = _save_classification(
            stage4_env["data_dir"],
            document,
            status="interrupted",
            page_results=(_completed_page(document, 1, eligible=False, kind="completed"),),
            terminal_reason="replaced later",
        )
        assert later.status == "interrupted"
        assert classification_snapshot_sha256(later) != original_digest

        snapshot = client.get(f"/api/v1/extraction-reviews/jobs/{local_job_id}/classification")
        assert snapshot.status_code == 200
        body = snapshot.json()["classification"]
        assert body["source"] == "job_snapshot"
        assert body["status"] == "completed"
        assert body["terminal_reason"] is None
        assert len(body["pages"]) == 3
        _wait_for(lambda: service.get_job(local_job_id).status.value in {"completed", "failed"})
    finally:
        _wait_for(lambda: _threads_idle(service), timeout=5.0)
        service.close()


def test_stage3_endpoints_unchanged_without_stage4(tmp_path: Path) -> None:
    data = tmp_path / "data"
    approved = tmp_path / "approved"
    data.mkdir()
    approved.mkdir()
    static = tmp_path / "static"
    static.mkdir()
    (static / "review.js").write_text(
        "export function mountExtractionReviewWorkspace() {}",
        encoding="utf-8",
    )
    (static / "review.css").write_text("/* test */", encoding="utf-8")
    app = create_app(
        data_dir=data,
        approved_documents_root=approved,
        static_dir=static,
        compose_stage4=False,
    )
    client = TestClient(app)
    jobs = client.get("/api/v1/extraction-reviews/jobs")
    assert jobs.status_code == 200
    assert jobs.json() == {"jobs": []}
    unavailable = client.get("/api/v1/extraction-reviews/approved-documents")
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "STAGE4_UNAVAILABLE"


def _classified_reviewable_client(tmp_path: Path) -> tuple[TestClient, Path, Path, str]:
    local_job_id = workspace_fixtures.LOCAL_JOB_ID
    data, approved = _workspace_build(tmp_path)
    html_path = next(approved.rglob("document.html"))
    document = prepare_reviewed_document(html_path)
    page_results = tuple(
        _completed_page(document, page.binding.page_number, eligible=True)
        for page in document.pages
    )
    state = CurrentClassificationState(
        reviewed_html=document.reviewed_html,
        status="completed",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        finished_at=FIXED_NOW,
        progress=ClassificationProgress(
            total_pages=len(document.pages),
            completed_pages=len(page_results),
            current_page_number=None,
        ),
        page_results=page_results,
        terminal_reason=None,
    )
    digest = classification_snapshot_sha256(state)
    job_path = data / JOBS_DIR_NAME / f"{local_job_id}.json"
    job = LocalLexicalJob.model_validate_json(job_path.read_text(encoding="utf-8"))
    classified = job.model_copy(
        update={
            "classified_extraction": ClassifiedExtractionContext(
                snapshot_sha256=digest,
                selected_page_numbers=tuple(page.binding.page_number for page in document.pages),
                classifier_policy_version=state.classifier_policy_version,
            )
        }
    )
    job_path.write_text(classified.model_dump_json(indent=2), encoding="utf-8")
    snapshot_dir = data / JOBS_DIR_NAME / local_job_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / CLASSIFICATION_SNAPSHOT_FILENAME
    snapshot_path.write_bytes(canonical_classification_snapshot_bytes(state))

    adapter = LocalStage4Adapter(
        data,
        approved,
        classification_service=FakeClassificationService(data),
        lexical_job_service=None,
        config_path=None,
    )
    app = FastAPI()
    mount_extraction_review(
        app,
        ExtractionReviewWorkspace(data, approved),
        stage4_adapter=adapter,
    )
    return TestClient(app), data, snapshot_path, local_job_id


def test_classified_snapshot_validated_before_save_and_approve(tmp_path: Path) -> None:
    client, data, snapshot_path, local_job_id = _classified_reviewable_client(tmp_path)
    opened = client.get(f"/api/v1/extraction-reviews/jobs/{local_job_id}")
    assert opened.status_code == 200
    body = opened.json()
    assert body["classification"] is not None
    assert body["classification"]["source"] == "job_snapshot"
    revision = body["current_revision_id"]
    finding_id = body["findings"][0]["finding_id"]
    page_number = body["findings"][0]["page_number"]

    saved = client.put(
        f"/api/v1/extraction-reviews/jobs/{local_job_id}",
        json={
            "expected_revision_id": revision,
            "edits": [
                {
                    "op": "patch_text",
                    "finding_id": finding_id,
                    "page_number": page_number,
                    "display_text": "patched-ok",
                }
            ],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["classification"]["source"] == "job_snapshot"
    assert saved.json()["findings"]
    patched_revision = saved.json()["current_revision_id"]
    assert patched_revision != revision

    snapshot_path.unlink()
    before = ExtractionReviewStore(data).load(local_job_id)
    assert before.current_revision_id == patched_revision
    assert before.approval is None

    rejected_save = client.put(
        f"/api/v1/extraction-reviews/jobs/{local_job_id}",
        json={
            "expected_revision_id": patched_revision,
            "edits": [
                {
                    "op": "patch_text",
                    "finding_id": finding_id,
                    "page_number": page_number,
                    "display_text": "should-not-apply",
                }
            ],
        },
    )
    assert rejected_save.status_code == 409
    assert rejected_save.json()["code"] == "CLASSIFICATION_SNAPSHOT_MISSING"
    after_save = ExtractionReviewStore(data).load(local_job_id)
    assert after_save.current_revision_id == patched_revision
    assert after_save.approval is None
    active = next(item for item in after_save.findings if item.finding_id == finding_id)
    assert active.current is not None
    assert active.current.display_text == "patched-ok"

    approved = client.post(
        f"/api/v1/extraction-reviews/jobs/{local_job_id}/approve",
        json={"expected_revision_id": patched_revision},
    )
    assert approved.status_code == 409
    assert approved.json()["code"] == "CLASSIFICATION_SNAPSHOT_MISSING"
    after_approve = ExtractionReviewStore(data).load(local_job_id)
    assert after_approve.approval is None
    assert after_approve.current_revision_id == patched_revision


def test_classified_snapshot_digest_and_malformed_reject_before_mutation(
    tmp_path: Path,
) -> None:
    client, data, snapshot_path, local_job_id = _classified_reviewable_client(tmp_path)
    opened = client.get(f"/api/v1/extraction-reviews/jobs/{local_job_id}").json()
    revision = opened["current_revision_id"]

    snapshot_path.write_text("{not-json", encoding="utf-8")
    malformed = client.put(
        f"/api/v1/extraction-reviews/jobs/{local_job_id}",
        json={"expected_revision_id": revision, "edits": []},
    )
    assert malformed.status_code == 409
    assert malformed.json()["code"] == "CLASSIFICATION_SNAPSHOT_INVALID"
    assert ExtractionReviewStore(data).load(local_job_id).current_revision_id == revision

    # Restore a valid shape but wrong digest.
    html_path = next((tmp_path / "approved").rglob("document.html"))
    document = prepare_reviewed_document(html_path)
    other = CurrentClassificationState(
        reviewed_html=document.reviewed_html,
        status="interrupted",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        finished_at=FIXED_NOW,
        progress=ClassificationProgress(
            total_pages=len(document.pages),
            completed_pages=0,
            current_page_number=None,
        ),
        page_results=(),
        terminal_reason="digest mismatch fixture",
    )
    snapshot_path.write_bytes(canonical_classification_snapshot_bytes(other))
    mismatched = client.post(
        f"/api/v1/extraction-reviews/jobs/{local_job_id}/approve",
        json={"expected_revision_id": revision},
    )
    assert mismatched.status_code == 409
    assert mismatched.json()["code"] == "CLASSIFICATION_SNAPSHOT_DIGEST_MISMATCH"
    stored = ExtractionReviewStore(data).load(local_job_id)
    assert stored.current_revision_id == revision
    assert stored.approval is None


def test_classified_snapshot_binding_mismatch_rejects_before_mutation(
    tmp_path: Path,
) -> None:
    client, data, snapshot_path, local_job_id = _classified_reviewable_client(tmp_path)
    opened = client.get(f"/api/v1/extraction-reviews/jobs/{local_job_id}")
    assert opened.status_code == 200
    body = opened.json()
    revision = body["current_revision_id"]
    finding_texts = [
        None if item["display_text"] is None else item["display_text"] for item in body["findings"]
    ]
    assert body["approval_state"] == "not_approved"

    html_path = next((tmp_path / "approved").rglob("document.html"))
    document = prepare_reviewed_document(html_path)
    foreign_binding = document.reviewed_html.model_copy(
        update={"html_sha256": "a" * 64, "job_id": "foreign-job-binding"}
    )
    foreign_state = CurrentClassificationState(
        reviewed_html=foreign_binding,
        status="interrupted",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        finished_at=FIXED_NOW,
        progress=ClassificationProgress(
            total_pages=len(document.pages),
            completed_pages=0,
            current_page_number=None,
        ),
        page_results=(),
        terminal_reason="binding mismatch fixture",
    )
    foreign_digest = classification_snapshot_sha256(foreign_state)
    # Digest on the job must match the foreign snapshot bytes; binding must not.
    snapshot_path.write_bytes(canonical_classification_snapshot_bytes(foreign_state))
    job_path = data / JOBS_DIR_NAME / f"{local_job_id}.json"
    job = LocalLexicalJob.model_validate_json(job_path.read_text(encoding="utf-8"))
    assert job.classified_extraction is not None
    assert job.reviewed_html is not None
    assert foreign_binding != job.reviewed_html
    job_path.write_text(
        job.model_copy(
            update={
                "classified_extraction": job.classified_extraction.model_copy(
                    update={"snapshot_sha256": foreign_digest}
                )
            }
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    assert (
        classification_snapshot_sha256(
            CurrentClassificationState.model_validate_json(
                snapshot_path.read_text(encoding="utf-8")
            )
        )
        == foreign_digest
    )

    before = ExtractionReviewStore(data).load(local_job_id)
    before_findings = tuple(
        (item.finding_id, None if item.current is None else item.current.display_text)
        for item in before.findings
    )

    rejected_save = client.put(
        f"/api/v1/extraction-reviews/jobs/{local_job_id}",
        json={
            "expected_revision_id": revision,
            "edits": [
                {
                    "op": "patch_text",
                    "finding_id": body["findings"][0]["finding_id"],
                    "page_number": body["findings"][0]["page_number"],
                    "display_text": "must-not-apply",
                }
            ],
        },
    )
    assert rejected_save.status_code == 409
    assert rejected_save.json()["code"] == "CLASSIFICATION_BINDING_MISMATCH"
    assert "sk-" not in rejected_save.json()["message"]
    assert "/" not in rejected_save.json()["message"]

    rejected_approve = client.post(
        f"/api/v1/extraction-reviews/jobs/{local_job_id}/approve",
        json={"expected_revision_id": revision},
    )
    assert rejected_approve.status_code == 409
    assert rejected_approve.json()["code"] == "CLASSIFICATION_BINDING_MISMATCH"

    after = ExtractionReviewStore(data).load(local_job_id)
    assert after.current_revision_id == revision
    assert after.approval is None
    assert after.approval_state.value == "not_approved"
    assert (
        tuple(
            (item.finding_id, None if item.current is None else item.current.display_text)
            for item in after.findings
        )
        == before_findings
    )
    assert finding_texts == [
        None if item.current is None else item.current.display_text for item in after.findings
    ]


def test_legacy_save_approve_unchanged_with_stage4_adapter(tmp_path: Path) -> None:
    local_job_id = workspace_fixtures.LOCAL_JOB_ID
    data, approved = _workspace_build(tmp_path)
    adapter = LocalStage4Adapter(
        data,
        approved,
        classification_service=FakeClassificationService(data),
        lexical_job_service=None,
        config_path=None,
    )
    app = FastAPI()
    mount_extraction_review(
        app,
        ExtractionReviewWorkspace(data, approved),
        stage4_adapter=adapter,
    )
    client = TestClient(app)
    opened = client.get(f"/api/v1/extraction-reviews/jobs/{local_job_id}").json()
    assert opened.get("classification") is None
    revision = opened["current_revision_id"]
    finding_id = opened["findings"][0]["finding_id"]
    page_number = opened["findings"][0]["page_number"]
    saved = client.put(
        f"/api/v1/extraction-reviews/jobs/{local_job_id}",
        json={
            "expected_revision_id": revision,
            "edits": [
                {
                    "op": "patch_text",
                    "finding_id": finding_id,
                    "page_number": page_number,
                    "display_text": "legacy-patched",
                }
            ],
        },
    )
    assert saved.status_code == 200
    assert saved.json().get("classification") is None
    approved_response = client.post(
        f"/api/v1/extraction-reviews/jobs/{local_job_id}/approve",
        json={"expected_revision_id": saved.json()["current_revision_id"]},
    )
    assert approved_response.status_code == 200
    assert approved_response.json()["approval_state"] == "approved"
    assert approved_response.json().get("classification") is None

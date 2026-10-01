"""S4.3 classified-full local lexical job submission."""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.extraction_review.approved_documents import DOCUMENT_HTML_NAME
from app.extraction_review.contracts import ExtractionReviewAction
from app.extraction_review.local_jobs import (
    CLASSIFICATION_SNAPSHOT_FILENAME,
    JOBS_DIR_NAME,
    NO_ELIGIBLE_PAGES_MESSAGE,
    RAW_RUNS_DIR_NAME,
    ClassifiedFullExtractionError,
    ClassifiedFullJobSubmitted,
    LocalJobStatus,
    LocalLexicalJobService,
    NoEligiblePagesForExtraction,
)
from app.extraction_review.store import REVIEWS_DIR_NAME
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
from app.page_classification.store import (
    PageClassificationStore,
    classification_snapshot_sha256,
)

PC_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "page_classification"
    / "fixtures"
    / "reviewed_html_v1.html"
)
PC_JOB = "job-page-class-1"
PC_REV = "rev-page-class-1"
CLASSIFIED_FIXED_NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


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


def _classified_stage2_executor(
    *,
    observed_allow_lists: list[tuple[int, ...]] | None = None,
    observed_restrictions: list[Stage4PageRestrictionProvenance] | None = None,
    observed_calls: list[str] | None = None,
) -> Any:
    def execute(
        config: EffectiveExecutionConfiguration,
        sink: FilesystemEvidenceSink,
        page_allow_list: tuple[int, ...],
        stage4_page_restriction: Stage4PageRestrictionProvenance,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        if observed_calls is not None:
            observed_calls.append("classified")
        if observed_allow_lists is not None:
            observed_allow_lists.append(page_allow_list)
        if observed_restrictions is not None:
            observed_restrictions.append(stage4_page_restriction)
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
            stage4_page_restriction=stage4_page_restriction,
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
        manifest_path.write_text("{}", encoding="utf-8")
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


def _ordinary_stage2_executor(
    *,
    observed_calls: list[str] | None = None,
) -> Any:
    def execute(
        config: EffectiveExecutionConfiguration,
        sink: FilesystemEvidenceSink,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        if observed_calls is not None:
            observed_calls.append("ordinary")
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
        manifest_path.write_text("{}", encoding="utf-8")
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
def classified_env(tmp_path: Path) -> dict[str, Path]:
    data_dir = tmp_path / "data"
    approved = tmp_path / "approved"
    data_dir.mkdir()
    approved.mkdir()
    config_path = _write_config(tmp_path / "config" / "execution.yaml")
    directory = approved / PC_JOB / PC_REV
    directory.mkdir(parents=True)
    (directory / DOCUMENT_HTML_NAME).write_bytes(PC_FIXTURE.read_bytes())
    return {
        "data_dir": data_dir,
        "approved": approved,
        "config_path": config_path,
    }


def _empty_classifier_responses() -> tuple[Any, Any, Any]:
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
    one, two, three = _empty_classifier_responses()
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
    finished = CLASSIFIED_FIXED_NOW if status != "running" else None
    current_page: int | None = None
    if status == "running" and len(page_results) < len(document.pages):
        current_page = document.pages[len(page_results)].binding.page_number
    state = CurrentClassificationState(
        reviewed_html=document.reviewed_html,
        status=status,  # type: ignore[arg-type]
        created_at=CLASSIFIED_FIXED_NOW,
        updated_at=CLASSIFIED_FIXED_NOW,
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


def test_classified_full_excludes_only_ineligible_pages(classified_env: dict[str, Path]) -> None:
    document = prepare_reviewed_document(
        classified_env["approved"] / PC_JOB / PC_REV / DOCUMENT_HTML_NAME
    )
    results = (
        _completed_page(document, 1, eligible=False, kind="completed"),
        _completed_page(document, 2, eligible=True, kind="completed"),
        _completed_page(document, 3, eligible=True, kind="needs_review", requires_review=True),
    )
    state = _save_classification(
        classified_env["data_dir"],
        document,
        status="completed",
        page_results=results,
    )
    observed_allow: list[tuple[int, ...]] = []
    observed_restriction: list[Stage4PageRestrictionProvenance] = []
    ordinary_calls: list[str] = []
    with LocalLexicalJobService(
        classified_env["data_dir"],
        execute_stage2=_ordinary_stage2_executor(observed_calls=ordinary_calls),
        execute_classified_stage2=_classified_stage2_executor(
            observed_allow_lists=observed_allow,
            observed_restrictions=observed_restriction,
        ),
        clock=lambda: CLASSIFIED_FIXED_NOW,
    ) as service:
        outcome = service.submit_classified_full_extraction(
            approved_documents_root=classified_env["approved"],
            job_id=PC_JOB,
            review_revision_id=PC_REV,
            config_path=classified_env["config_path"],
        )
        assert isinstance(outcome, ClassifiedFullJobSubmitted)
        job = outcome.job
        assert job.action is ExtractionReviewAction.EXTRACT_ALL
        assert job.classified_extraction is not None
        assert job.classified_extraction.selected_page_numbers == (2, 3)
        digest = classification_snapshot_sha256(state)
        assert job.classified_extraction.snapshot_sha256 == digest
        snapshot_path = service.classification_snapshot_path(job.local_job_id)
        assert snapshot_path.is_file()
        assert snapshot_path.name == CLASSIFICATION_SNAPSHOT_FILENAME
        assert _sha256(snapshot_path.read_bytes()) == digest
        _wait_for(lambda: service.get_job(job.local_job_id).status is LocalJobStatus.COMPLETED)
        completed = service.get_job(job.local_job_id)

    assert ordinary_calls == []
    assert observed_allow == [(2, 3)]
    assert len(observed_restriction) == 1
    restriction = observed_restriction[0]
    assert restriction.selected_page_numbers == (2, 3)
    assert restriction.classification_snapshot_sha256 == digest
    assert completed.run is not None
    assert completed.run.stage4_page_restriction == restriction
    assert completed.extraction is not None

    with LocalLexicalJobService(
        classified_env["data_dir"],
        execute_stage2=_ordinary_stage2_executor(observed_calls=ordinary_calls),
    ) as service:
        plain = service.submit(
            approved_documents_root=classified_env["approved"],
            job_id=PC_JOB,
            review_revision_id=PC_REV,
            config_path=classified_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(lambda: service.get_job(plain.local_job_id).status is LocalJobStatus.COMPLETED)
        plain_job = service.get_job(plain.local_job_id)
    assert plain_job.classified_extraction is None
    assert "classified_extraction" not in plain_job.model_dump(mode="json")
    assert ordinary_calls == ["ordinary"]
    assert "stage4_page_restriction" not in plain_job.run.model_dump(mode="json")  # type: ignore[union-attr]


def test_classified_full_keeps_incomplete_and_unprocessed_pages(
    classified_env: dict[str, Path],
) -> None:
    document = prepare_reviewed_document(
        classified_env["approved"] / PC_JOB / PC_REV / DOCUMENT_HTML_NAME
    )
    page1 = _completed_page(document, 1, eligible=True, kind="incomplete")
    page2 = _completed_page(document, 2, eligible=True, kind="empty")
    state = _save_classification(
        classified_env["data_dir"],
        document,
        status="interrupted",
        page_results=(page1, page2),
        terminal_reason="page classification was interrupted by service restart",
    )
    observed_allow: list[tuple[int, ...]] = []
    with LocalLexicalJobService(
        classified_env["data_dir"],
        execute_classified_stage2=_classified_stage2_executor(
            observed_allow_lists=observed_allow,
        ),
    ) as service:
        outcome = service.submit_classified_full_extraction(
            approved_documents_root=classified_env["approved"],
            job_id=PC_JOB,
            review_revision_id=PC_REV,
            config_path=classified_env["config_path"],
        )
        assert isinstance(outcome, ClassifiedFullJobSubmitted)
        assert outcome.job.classified_extraction is not None
        assert outcome.job.classified_extraction.selected_page_numbers == (1, 2, 3)
        snapshot_before = service.classification_snapshot_path(
            outcome.job.local_job_id
        ).read_bytes()
        _wait_for(
            lambda: service.get_job(outcome.job.local_job_id).status is LocalJobStatus.COMPLETED
        )
        _save_classification(
            classified_env["data_dir"],
            document,
            status="completed",
            page_results=(
                _completed_page(document, 1, eligible=False, kind="completed"),
                _completed_page(document, 2, eligible=True),
                _completed_page(document, 3, eligible=True),
            ),
        )
        assert (
            service.classification_snapshot_path(outcome.job.local_job_id).read_bytes()
            == snapshot_before
        )
        assert classification_snapshot_sha256(state) == _sha256(snapshot_before)
    assert observed_allow == [(1, 2, 3)]


def test_classified_full_rejects_running_and_missing(classified_env: dict[str, Path]) -> None:
    document = prepare_reviewed_document(
        classified_env["approved"] / PC_JOB / PC_REV / DOCUMENT_HTML_NAME
    )
    invoked = {"count": 0}

    def tracking_classified(
        config: EffectiveExecutionConfiguration,
        sink: FilesystemEvidenceSink,
        page_allow_list: tuple[int, ...],
        stage4_page_restriction: Stage4PageRestrictionProvenance,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        invoked["count"] += 1
        return _classified_stage2_executor()(
            config,
            sink,
            page_allow_list,
            stage4_page_restriction,
        )

    with LocalLexicalJobService(
        classified_env["data_dir"],
        execute_classified_stage2=tracking_classified,
    ) as service:
        with pytest.raises(ClassifiedFullExtractionError) as missing:
            service.submit_classified_full_extraction(
                approved_documents_root=classified_env["approved"],
                job_id=PC_JOB,
                review_revision_id=PC_REV,
                config_path=classified_env["config_path"],
            )
        assert missing.value.code == "CLASSIFICATION_MISSING"

        _save_classification(
            classified_env["data_dir"],
            document,
            status="running",
            page_results=(),
        )
        with pytest.raises(ClassifiedFullExtractionError) as running:
            service.submit_classified_full_extraction(
                approved_documents_root=classified_env["approved"],
                job_id=PC_JOB,
                review_revision_id=PC_REV,
                config_path=classified_env["config_path"],
            )
        assert running.value.code == "CLASSIFICATION_RUNNING"
    assert invoked["count"] == 0
    assert not any((classified_env["data_dir"] / JOBS_DIR_NAME).glob("*.json"))


def test_classified_full_zero_eligible_is_non_error(classified_env: dict[str, Path]) -> None:
    document = prepare_reviewed_document(
        classified_env["approved"] / PC_JOB / PC_REV / DOCUMENT_HTML_NAME
    )
    results = tuple(
        _completed_page(document, page_number, eligible=False, kind="completed")
        for page_number in (1, 2, 3)
    )
    _save_classification(
        classified_env["data_dir"],
        document,
        status="completed",
        page_results=results,
    )
    invoked = {"count": 0}

    def tracking_classified(
        config: EffectiveExecutionConfiguration,
        sink: FilesystemEvidenceSink,
        page_allow_list: tuple[int, ...],
        stage4_page_restriction: Stage4PageRestrictionProvenance,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        invoked["count"] += 1
        return _classified_stage2_executor()(
            config,
            sink,
            page_allow_list,
            stage4_page_restriction,
        )

    with LocalLexicalJobService(
        classified_env["data_dir"],
        execute_classified_stage2=tracking_classified,
    ) as service:
        outcome = service.submit_classified_full_extraction(
            approved_documents_root=classified_env["approved"],
            job_id=PC_JOB,
            review_revision_id=PC_REV,
            config_path=classified_env["config_path"],
        )
    assert isinstance(outcome, NoEligiblePagesForExtraction)
    assert outcome.message == NO_ELIGIBLE_PAGES_MESSAGE
    assert invoked["count"] == 0
    assert list((classified_env["data_dir"] / JOBS_DIR_NAME).glob("*.json")) == []
    assert not any(path.is_dir() for path in (classified_env["data_dir"] / JOBS_DIR_NAME).glob("*"))
    assert list((classified_env["data_dir"] / RAW_RUNS_DIR_NAME).iterdir()) == []
    assert list((classified_env["data_dir"] / REVIEWS_DIR_NAME).glob("*")) == []


def test_classified_job_does_not_invoke_ordinary_stage2_executor(
    classified_env: dict[str, Path],
) -> None:
    document = prepare_reviewed_document(
        classified_env["approved"] / PC_JOB / PC_REV / DOCUMENT_HTML_NAME
    )
    _save_classification(
        classified_env["data_dir"],
        document,
        status="completed",
        page_results=(
            _completed_page(document, 1, eligible=True),
            _completed_page(document, 2, eligible=True),
            _completed_page(document, 3, eligible=True),
        ),
    )
    ordinary_calls: list[str] = []
    classified_calls: list[str] = []
    with LocalLexicalJobService(
        classified_env["data_dir"],
        execute_stage2=_ordinary_stage2_executor(observed_calls=ordinary_calls),
        execute_classified_stage2=_classified_stage2_executor(
            observed_calls=classified_calls,
        ),
    ) as service:
        outcome = service.submit_classified_full_extraction(
            approved_documents_root=classified_env["approved"],
            job_id=PC_JOB,
            review_revision_id=PC_REV,
            config_path=classified_env["config_path"],
        )
        assert isinstance(outcome, ClassifiedFullJobSubmitted)
        _wait_for(
            lambda: service.get_job(outcome.job.local_job_id).status is LocalJobStatus.COMPLETED
        )
    assert ordinary_calls == []
    assert classified_calls == ["classified"]

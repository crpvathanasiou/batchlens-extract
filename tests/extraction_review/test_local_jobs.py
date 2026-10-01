"""U2.2 local background lexical job service."""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.extraction_review.approved_documents import DOCUMENT_HTML_NAME
from app.extraction_review.contracts import ExtractionReviewAction
from app.extraction_review.local_jobs import (
    JOBS_DIR_NAME,
    RAW_RUNS_DIR_NAME,
    LocalJobPhase,
    LocalJobStatus,
    LocalLexicalJob,
    LocalLexicalJobNotFoundError,
    LocalLexicalJobService,
    LocalLexicalJobServiceAlreadyActiveError,
    LocalLexicalJobServiceBusyError,
)
from app.extraction_review.store import (
    CURRENT_REVIEW_FILENAME,
    REVIEWS_DIR_NAME,
    derive_workspace_key,
)
from app.lexical_extraction.configuration import EffectiveExecutionConfiguration
from app.lexical_extraction.contracts import (
    Component,
    ComponentResult,
    ExtractionOutcome,
    ExtractionOutcomeRecord,
    FinalManifestClaim,
    KnowledgeSnapshotIdentity,
    Preset,
    PublicationRecord,
    PublicationStatus,
    RunProvenance,
    SafeStructuredError,
)
from app.lexical_extraction.monitoring import RunMonitoringAccumulator
from app.lexical_extraction.publication import (
    FilesystemEvidenceSink,
    PublicationResult,
)
from app.lexical_extraction.runner import LexicalRunResult

REVISION = "00000000-0000-4000-8000-0000000000aa"
DOC_JOB = "job-1"
FIXED_NOW = datetime(2026, 9, 29, 15, 0, 0, tzinfo=UTC)


def _root(
    *,
    version: str = "1",
    job_id: str = DOC_JOB,
    revision_id: str = REVISION,
    generation: str = "1",
    status: str = "SUCCEEDED",
) -> str:
    return (
        "<!doctype html>"
        f'<html data-review-html-version="{version}" data-job-id="{job_id}" '
        f'data-review-revision-id="{revision_id}" data-review-generation="{generation}" '
        f'data-conversion-status="{status}">'
    )


def _wrap(body: str, **root_kwargs: str) -> str:
    return (
        f"{_root(**root_kwargs)}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body>'
        '<header class="summary" data-generated="true"><h1>Reviewed document</h1></header>'
        f"<main>{body}</main></body></html>"
    )


def _minimal_body() -> str:
    return '<section class="page" id="source-page-1" data-page="1"></section>'


def _write_approved_document(
    root: Path,
    *,
    job_id: str = DOC_JOB,
    revision: str = REVISION,
) -> Path:
    html = _wrap(_minimal_body(), job_id=job_id, revision_id=revision)
    directory = root / job_id / revision
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / DOCUMENT_HTML_NAME
    path.write_bytes(html.encode("utf-8"))
    return path


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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _wait_for(
    predicate: Any,
    *,
    timeout: float = 5.0,
    interval: float = 0.02,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition not met before timeout")


def _empty_monitoring() -> Any:
    return RunMonitoringAccumulator().freeze()


def _component_results(
    resolved: tuple[Component, ...],
    overall: ExtractionOutcome,
) -> tuple[ComponentResult, ...]:
    if overall is ExtractionOutcome.PARTIAL:
        if not resolved:
            return ()
        first, *rest = resolved
        items = [
            ComponentResult(
                component=first,
                outcome=ExtractionOutcome.PARTIAL,
                match_count=1,
            )
        ]
        items.extend(
            ComponentResult(
                component=component,
                outcome=ExtractionOutcome.COMPLETED,
                match_count=1,
            )
            for component in rest
        )
        return tuple(items)
    if overall is ExtractionOutcome.FAILED:
        return tuple(
            ComponentResult(
                component=component,
                outcome=ExtractionOutcome.FAILED,
                error=SafeStructuredError(
                    code="COMPONENT_FAILED",
                    message="component failed",
                    component=component,
                    retryable=False,
                ),
            )
            for component in resolved
        )
    return tuple(
        ComponentResult(
            component=component,
            outcome=ExtractionOutcome.COMPLETED,
            match_count=1,
        )
        for component in resolved
    )


def _success_executor(
    *,
    overall: ExtractionOutcome = ExtractionOutcome.COMPLETED,
    block_until: threading.Event | None = None,
    started: threading.Event | None = None,
    fail_publication: bool = False,
    observed_config: list[EffectiveExecutionConfiguration] | None = None,
    observed_call_shapes: list[tuple[int, ...]] | None = None,
) -> Any:
    def execute(
        config: EffectiveExecutionConfiguration,
        sink: FilesystemEvidenceSink,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        if observed_config is not None:
            observed_config.append(config)
        if observed_call_shapes is not None:
            observed_call_shapes.append((2,))
        if started is not None:
            started.set()
        if block_until is not None:
            assert block_until.wait(timeout=5.0)
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
            overall=overall,
            components=_component_results(config.resolved_components, overall),
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
        if fail_publication:
            return run_result, PublicationResult(
                run_id=run_id,
                run_directory=sink.run_directory,
                publication=PublicationRecord(status=PublicationStatus.FAILED),
                manifest_path=None,
                artifacts=(),
                exit_code=3,
                error=SafeStructuredError(
                    code="MANIFEST_PUBLICATION_FAILED",
                    message="final manifest publication failed",
                    retryable=False,
                ),
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
            exit_code=0 if overall is ExtractionOutcome.COMPLETED else 1,
            error=None,
        )

    return execute


@pytest.fixture
def job_env(tmp_path: Path) -> dict[str, Path]:
    data_dir = tmp_path / "data"
    approved = tmp_path / "approved"
    approved.mkdir()
    _write_approved_document(approved)
    config_path = _write_config(tmp_path / "configs" / "execution.yaml")
    data_dir.mkdir()
    return {
        "data_dir": data_dir,
        "approved": approved,
        "config_path": config_path,
    }


def test_submit_persists_queued_before_worker_completes(job_env: dict[str, Path]) -> None:
    gate = threading.Event()
    started = threading.Event()
    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=_success_executor(block_until=gate, started=started),
        clock=lambda: FIXED_NOW,
    ) as service:
        job = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        assert job.status is LocalJobStatus.QUEUED
        assert job.phase is LocalJobPhase.QUEUED
        assert job.fuzzy_enabled is False

        path = service.jobs_dir / f"{job.local_job_id}.json"
        assert path.is_file()
        on_disk = LocalLexicalJob.model_validate_json(path.read_text(encoding="utf-8"))
        assert on_disk.status is LocalJobStatus.QUEUED

        assert started.wait(timeout=5.0)
        gate.set()
        _wait_for(lambda: service.get_job(job.local_job_id).status is LocalJobStatus.COMPLETED)


def test_completed_job_persists_truthful_facts(job_env: dict[str, Path]) -> None:
    observed: list[EffectiveExecutionConfiguration] = []
    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=_success_executor(observed_config=observed),
        clock=lambda: FIXED_NOW,
    ) as service:
        queued = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
            fuzzy_enabled=False,
        )
        _wait_for(lambda: service.get_job(queued.local_job_id).status is LocalJobStatus.COMPLETED)
        job = service.get_job(queued.local_job_id)

    assert job.action is ExtractionReviewAction.EXTRACT_MATERIALS
    assert job.fuzzy_enabled is False
    assert job.reviewed_html is not None
    assert job.reviewed_html.job_id == DOC_JOB
    assert job.reviewed_html.review_revision_id == REVISION
    assert len(job.reviewed_html.html_sha256) == 64
    assert job.run is not None
    assert job.run.requested_presets == (Preset.MATERIALS_WITH_QUANTITIES,)
    assert job.run.fuzzy_requested is False
    assert job.extraction is not None
    assert job.extraction.overall is ExtractionOutcome.COMPLETED
    assert job.publication is not None
    assert job.publication.status is PublicationStatus.COMPLETED
    assert job.published_manifest is not None
    assert job.raw_run_relative_dir is not None
    raw_dir = job_env["data_dir"] / RAW_RUNS_DIR_NAME / job.raw_run_relative_dir
    assert raw_dir.is_dir()
    manifest_path = raw_dir / "manifest.json"
    assert job.published_manifest.manifest_sha256 == _sha256(manifest_path.read_bytes())
    assert observed
    assert observed[0].extraction.presets == (Preset.MATERIALS_WITH_QUANTITIES,)
    assert observed[0].extraction.components == ()
    assert observed[0].extraction.fuzzy_enabled is False
    assert observed[0].output.directory == (job_env["data_dir"] / RAW_RUNS_DIR_NAME).resolve()


def test_partial_extraction_with_completed_publication(job_env: dict[str, Path]) -> None:
    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=_success_executor(overall=ExtractionOutcome.PARTIAL),
    ) as service:
        queued = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(lambda: service.get_job(queued.local_job_id).status is LocalJobStatus.COMPLETED)
        job = service.get_job(queued.local_job_id)

    assert job.status is LocalJobStatus.COMPLETED
    assert job.extraction is not None
    assert job.extraction.overall is ExtractionOutcome.PARTIAL
    assert job.publication is not None
    assert job.publication.status is PublicationStatus.COMPLETED
    assert job.published_manifest is not None


def test_failed_selection_becomes_safe_failed_job(job_env: dict[str, Path]) -> None:
    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=_success_executor(),
    ) as service:
        queued = service.submit(
            approved_documents_root=job_env["approved"],
            job_id="missing-job",
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(lambda: service.get_job(queued.local_job_id).status is LocalJobStatus.FAILED)
        job = service.get_job(queued.local_job_id)

    assert job.status is LocalJobStatus.FAILED
    assert job.phase is LocalJobPhase.FAILED
    assert job.error is not None
    assert job.error.code == "DOCUMENT_NOT_FOUND"
    assert str(job_env["approved"]) not in job.error.message
    assert job.published_manifest is None


def test_failed_configuration_becomes_safe_failed_job(job_env: dict[str, Path]) -> None:
    bad_config = job_env["config_path"].parent / "bad.yaml"
    bad_config.write_text("schema_version: 2\n", encoding="utf-8")
    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=_success_executor(),
    ) as service:
        queued = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=bad_config,
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(lambda: service.get_job(queued.local_job_id).status is LocalJobStatus.FAILED)
        job = service.get_job(queued.local_job_id)

    assert job.error is not None
    assert job.error.code == "CONFIGURATION_ERROR"
    assert str(bad_config) not in job.error.message


def test_failed_publication_becomes_safe_failed_job(job_env: dict[str, Path]) -> None:
    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=_success_executor(fail_publication=True),
    ) as service:
        queued = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(lambda: service.get_job(queued.local_job_id).status is LocalJobStatus.FAILED)
        job = service.get_job(queued.local_job_id)

    assert job.status is LocalJobStatus.FAILED
    assert job.error is not None
    assert job.error.code == "MANIFEST_PUBLICATION_FAILED"
    assert job.publication is not None
    assert job.publication.status is PublicationStatus.FAILED
    assert job.published_manifest is None


def test_fresh_service_loads_terminal_jobs(job_env: dict[str, Path]) -> None:
    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=_success_executor(),
    ) as service:
        queued = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_UNIT_OPERATIONS,
            fuzzy_enabled=True,
        )
        _wait_for(lambda: service.get_job(queued.local_job_id).status is LocalJobStatus.COMPLETED)
        first = service.get_job(queued.local_job_id)

    with LocalLexicalJobService(job_env["data_dir"], execute_stage2=_success_executor()) as service:
        loaded = service.get_job(first.local_job_id)

    assert loaded == first
    assert loaded.fuzzy_enabled is True
    assert loaded.action is ExtractionReviewAction.EXTRACT_UNIT_OPERATIONS


def test_restart_marks_abandoned_jobs_interrupted(job_env: dict[str, Path]) -> None:
    jobs_dir = job_env["data_dir"] / JOBS_DIR_NAME
    jobs_dir.mkdir(parents=True)
    queued_id = str(uuid.uuid4())
    running_id = str(uuid.uuid4())
    for local_id, status, phase in (
        (queued_id, LocalJobStatus.QUEUED, LocalJobPhase.QUEUED),
        (running_id, LocalJobStatus.RUNNING, LocalJobPhase.RUNNING_EXTRACTION),
    ):
        job = LocalLexicalJob(
            local_job_id=local_id,
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
            fuzzy_enabled=False,
            status=status,
            phase=phase,
            submitted_at=FIXED_NOW,
            started_at=FIXED_NOW if status is LocalJobStatus.RUNNING else None,
        )
        (jobs_dir / f"{local_id}.json").write_text(
            job.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

    with LocalLexicalJobService(job_env["data_dir"]) as service:
        queued = service.get_job(queued_id)
        running = service.get_job(running_id)

    assert queued.status is LocalJobStatus.INTERRUPTED
    assert queued.phase is LocalJobPhase.INTERRUPTED
    assert queued.error is not None
    assert queued.error.code == "JOB_INTERRUPTED"
    assert running.status is LocalJobStatus.INTERRUPTED
    assert running.error is not None
    assert running.error.code == "JOB_INTERRUPTED"


def test_only_one_active_service_per_data_directory(job_env: dict[str, Path]) -> None:
    with LocalLexicalJobService(job_env["data_dir"]) as first:
        with pytest.raises(LocalLexicalJobServiceAlreadyActiveError):
            LocalLexicalJobService(job_env["data_dir"])
        assert first.data_dir == job_env["data_dir"].resolve()


def test_jobs_do_not_touch_current_review_or_approve(job_env: dict[str, Path]) -> None:
    review_dir = job_env["data_dir"] / REVIEWS_DIR_NAME / derive_workspace_key(DOC_JOB)
    review_dir.mkdir(parents=True)
    review_path = review_dir / CURRENT_REVIEW_FILENAME
    original = b'{"sentinel": true, "approval": null}\n'
    review_path.write_bytes(original)

    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=_success_executor(),
    ) as service:
        queued = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_ALL,
        )
        _wait_for(lambda: service.get_job(queued.local_job_id).status is LocalJobStatus.COMPLETED)
        job = service.get_job(queued.local_job_id)

    assert review_path.read_bytes() == original
    assert job.status is LocalJobStatus.COMPLETED
    assert not hasattr(job, "approval")


def test_no_sqlite_retry_ledger_or_history_files(job_env: dict[str, Path]) -> None:
    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=_success_executor(),
    ) as service:
        queued = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_EQUIPMENT,
        )
        _wait_for(lambda: service.get_job(queued.local_job_id).status is LocalJobStatus.COMPLETED)

    created = {
        path.relative_to(job_env["data_dir"]).as_posix() for path in job_env["data_dir"].rglob("*")
    }
    assert not any(name.endswith(".sqlite") or name.endswith(".db") for name in created)
    assert not any("retry" in name or "history" in name for name in created)
    assert any(name.startswith(f"{JOBS_DIR_NAME}/") and name.endswith(".json") for name in created)
    assert any(name.startswith(f"{RAW_RUNS_DIR_NAME}/") for name in created)


def test_get_job_not_found(job_env: dict[str, Path]) -> None:
    with LocalLexicalJobService(job_env["data_dir"]) as service:
        with pytest.raises(LocalLexicalJobNotFoundError):
            service.get_job(str(uuid.uuid4()))
        with pytest.raises(LocalLexicalJobNotFoundError):
            service.get_job("../escape")


def test_failed_executor_becomes_safe_failed_job(job_env: dict[str, Path]) -> None:
    def boom(
        _config: EffectiveExecutionConfiguration,
        _sink: FilesystemEvidenceSink,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        raise RuntimeError(r"secret path C:\Users\secret\file")

    with LocalLexicalJobService(job_env["data_dir"], execute_stage2=boom) as service:
        queued = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(lambda: service.get_job(queued.local_job_id).status is LocalJobStatus.FAILED)
        job = service.get_job(queued.local_job_id)

    assert job.error is not None
    assert job.error.code == "UNEXPECTED_FAILURE"
    assert job.error.message == "local job failed unexpectedly"
    assert r"C:\Users\secret" not in job.error.message
    assert "RuntimeError" not in job.error.message


def test_one_execution_at_a_time_per_data_directory(job_env: dict[str, Path]) -> None:
    first_entered = threading.Event()
    first_release = threading.Event()
    second_entered = threading.Event()
    stage2_entries: list[str] = []
    entry_lock = threading.Lock()

    def execute(
        config: EffectiveExecutionConfiguration,
        sink: FilesystemEvidenceSink,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        with entry_lock:
            stage2_entries.append(str(config.input.reviewed_html_path))
            index = len(stage2_entries)
        if index == 1:
            first_entered.set()
            assert first_release.wait(timeout=5.0)
        else:
            second_entered.set()
        return _success_executor()(config, sink)

    service = LocalLexicalJobService(job_env["data_dir"], execute_stage2=execute)
    try:
        first = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        second = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_EQUIPMENT,
        )
        assert first_entered.wait(timeout=5.0)
        _wait_for(lambda: service.get_job(first.local_job_id).status is LocalJobStatus.RUNNING)
        assert service.get_job(second.local_job_id).status is LocalJobStatus.QUEUED
        assert service.get_job(second.local_job_id).phase is LocalJobPhase.QUEUED
        assert len(stage2_entries) == 1
        assert not second_entered.is_set()

        first_release.set()
        _wait_for(lambda: service.get_job(first.local_job_id).status is LocalJobStatus.COMPLETED)
        _wait_for(lambda: service.get_job(second.local_job_id).status is LocalJobStatus.COMPLETED)
        assert second_entered.wait(timeout=5.0)
        assert len(stage2_entries) == 2
        completed_second = service.get_job(second.local_job_id)
        assert completed_second.action is ExtractionReviewAction.EXTRACT_EQUIPMENT
    finally:
        service.close()


def test_close_refuses_while_workers_active(job_env: dict[str, Path]) -> None:
    gate = threading.Event()
    started = threading.Event()
    service = LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=_success_executor(block_until=gate, started=started),
    )
    job = service.submit(
        approved_documents_root=job_env["approved"],
        job_id=DOC_JOB,
        review_revision_id=REVISION,
        config_path=job_env["config_path"],
        action=ExtractionReviewAction.EXTRACT_MATERIALS,
    )
    assert started.wait(timeout=5.0)
    with pytest.raises(LocalLexicalJobServiceBusyError):
        service.close()
    with pytest.raises(LocalLexicalJobServiceAlreadyActiveError):
        LocalLexicalJobService(job_env["data_dir"])

    gate.set()
    _wait_for(lambda: service.get_job(job.local_job_id).status is LocalJobStatus.COMPLETED)
    service.close()
    with LocalLexicalJobService(job_env["data_dir"]) as replacement:
        assert replacement.data_dir == job_env["data_dir"].resolve()


def test_failed_run_without_raw_dir_registers_none(job_env: dict[str, Path]) -> None:
    def execute_without_run_dir(
        _config: EffectiveExecutionConfiguration,
        sink: FilesystemEvidenceSink,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        run_id = str(uuid.uuid4())
        missing = sink.output_directory / run_id
        run_result = LexicalRunResult(
            run_id=run_id,
            validated_input=None,
            knowledge=None,
            provenance=None,
            extraction=None,
            pre_validation=None,
            monitoring=_empty_monitoring(),
            run_error=SafeStructuredError(
                code="SINK_BEGIN_FAILED",
                message=rf"could not create {missing} under C:\secret\output",
                retryable=False,
            ),
        )
        return run_result, PublicationResult(
            run_id=run_id,
            run_directory=missing,
            publication=PublicationRecord(status=PublicationStatus.FAILED),
            manifest_path=None,
            artifacts=(),
            exit_code=3,
            error=SafeStructuredError(
                code="PUBLICATION_STATE",
                message=rf"publication failed for {missing}",
                retryable=False,
            ),
        )

    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=execute_without_run_dir,
    ) as service:
        queued = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(lambda: service.get_job(queued.local_job_id).status is LocalJobStatus.FAILED)
        job = service.get_job(queued.local_job_id)

    assert job.raw_run_relative_dir is None
    assert job.error is not None
    assert job.error.code == "PUBLICATION_STATE"
    assert job.error.message == "Stage 2 publication failed"
    assert "secret" not in job.error.message
    assert "\\" not in job.error.message
    assert str(job_env["data_dir"]) not in job.error.message


def test_persisted_errors_contain_no_local_paths(job_env: dict[str, Path]) -> None:
    paths = [
        str(job_env["approved"]),
        str(job_env["config_path"]),
        str(job_env["data_dir"]),
        str((job_env["data_dir"] / RAW_RUNS_DIR_NAME).resolve()),
    ]

    def assert_safe(job: LocalLexicalJob) -> None:
        assert job.error is not None
        for path in paths:
            assert path not in job.error.message
        assert ":\\" not in job.error.message
        assert "/Users/" not in job.error.message

    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=_success_executor(),
    ) as service:
        selection = service.submit(
            approved_documents_root=job_env["approved"],
            job_id="missing-job",
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(lambda: service.get_job(selection.local_job_id).status is LocalJobStatus.FAILED)
        selection_job = service.get_job(selection.local_job_id)
        assert_safe(selection_job)
        assert selection_job.error is not None
        assert selection_job.error.code == "DOCUMENT_NOT_FOUND"

    def runner_boom(
        _config: EffectiveExecutionConfiguration,
        _sink: FilesystemEvidenceSink,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        from app.lexical_extraction.runner import LexicalRunnerError

        raise LexicalRunnerError(
            "SINK_WRITE_FAILED",
            rf"evidence sink write failed at {job_env['data_dir'] / 'bad'}",
        )

    with LocalLexicalJobService(job_env["data_dir"], execute_stage2=runner_boom) as service:
        runner_job = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(lambda: service.get_job(runner_job.local_job_id).status is LocalJobStatus.FAILED)
        failed = service.get_job(runner_job.local_job_id)
        assert_safe(failed)
        assert failed.error is not None
        assert failed.error.code == "SINK_WRITE_FAILED"
        assert failed.error.message == "Stage 2 extraction failed"

    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=_success_executor(fail_publication=True),
    ) as service:
        publication_job = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(
            lambda: service.get_job(publication_job.local_job_id).status is LocalJobStatus.FAILED
        )
        failed = service.get_job(publication_job.local_job_id)
        assert_safe(failed)
        assert failed.error is not None
        assert failed.error.code == "MANIFEST_PUBLICATION_FAILED"
        assert failed.error.message == "Stage 2 publication failed"

    def unexpected(
        _config: EffectiveExecutionConfiguration,
        _sink: FilesystemEvidenceSink,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        raise ValueError(f"explode at {job_env['approved']}")

    with LocalLexicalJobService(job_env["data_dir"], execute_stage2=unexpected) as service:
        unexpected_job = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(
            lambda: service.get_job(unexpected_job.local_job_id).status is LocalJobStatus.FAILED
        )
        failed = service.get_job(unexpected_job.local_job_id)
        assert_safe(failed)
        assert failed.error is not None
        assert failed.error.code == "UNEXPECTED_FAILURE"
        assert failed.error.message == "local job failed unexpectedly"


def test_ordinary_submit_uses_legacy_two_argument_stage2_executor(
    job_env: dict[str, Path],
) -> None:
    observed_shapes: list[int] = []

    def legacy_executor(
        config: EffectiveExecutionConfiguration,
        sink: FilesystemEvidenceSink,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        observed_shapes.append(2)
        return _success_executor()(config, sink)

    with LocalLexicalJobService(
        job_env["data_dir"],
        execute_stage2=legacy_executor,
    ) as service:
        queued = service.submit(
            approved_documents_root=job_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=job_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(lambda: service.get_job(queued.local_job_id).status is LocalJobStatus.COMPLETED)
        job = service.get_job(queued.local_job_id)

    assert observed_shapes == [2]
    assert job.classified_extraction is None
    assert "classified_extraction" not in job.model_dump(mode="json")
    assert job.run is not None
    assert "stage4_page_restriction" not in job.run.model_dump(mode="json")

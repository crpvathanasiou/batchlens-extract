"""Focused regression coverage for the Stage 3 local harness."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from argparse import Namespace
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.extraction_review.approved_documents import DOCUMENT_HTML_NAME
from app.extraction_review.contracts import ExtractionReviewAction
from app.extraction_review.local_jobs import (
    LocalJobPhase,
    LocalJobStatus,
    LocalLexicalJob,
    LocalLexicalJobService,
    Stage2Execute,
)
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
)
from app.lexical_extraction.monitoring import RunMonitoringAccumulator
from app.lexical_extraction.publication import FilesystemEvidenceSink, PublicationResult
from app.lexical_extraction.runner import LexicalRunResult
from tests.extraction_review.local_harness import (
    create_app,
    main,
    missing_run_extraction_args,
    parser,
    run_extraction_job,
)

DOC_JOB = "job-1"
REVISION = "00000000-0000-4000-8000-0000000000aa"
FIXED_NOW = datetime(2026, 9, 29, 15, 0, 0, tzinfo=UTC)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _root(
    *,
    job_id: str = DOC_JOB,
    revision_id: str = REVISION,
) -> str:
    return (
        "<!doctype html>"
        f'<html data-review-html-version="1" data-job-id="{job_id}" '
        f'data-review-revision-id="{revision_id}" data-review-generation="1" '
        'data-conversion-status="SUCCEEDED">'
    )


def _write_approved_document(root: Path) -> Path:
    body = '<section class="page" id="source-page-1" data-page="1"></section>'
    html = (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body>'
        '<header class="summary" data-generated="true"><h1>Reviewed document</h1></header>'
        f"<main>{body}</main></body></html>"
    )
    directory = root / DOC_JOB / REVISION
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


def _wait_for(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met before timeout")


def _empty_monitoring() -> Any:
    return RunMonitoringAccumulator().freeze()


def _success_executor() -> Stage2Execute:
    def execute(
        config: EffectiveExecutionConfiguration,
        sink: FilesystemEvidenceSink,
    ) -> tuple[LexicalRunResult, PublicationResult]:
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
        manifest_id = f"manifest-{run_id}"
        manifest_path = sink.run_directory / "manifest.json"
        manifest_path.write_bytes(
            json.dumps({"manifest_id": manifest_id, "run_id": run_id}).encode("utf-8")
        )
        publication = PublicationRecord(
            status=PublicationStatus.COMPLETED,
            final_manifest=FinalManifestClaim(manifest_id=manifest_id),
        )
        return run_result, PublicationResult(
            run_id=run_id,
            run_directory=sink.run_directory,
            publication=publication,
            manifest_path=manifest_path,
            artifacts=(),
            exit_code=0,
            error=None,
        )

    return execute


def _fail_executor() -> Stage2Execute:
    def execute(
        config: EffectiveExecutionConfiguration,
        sink: FilesystemEvidenceSink,
    ) -> tuple[LexicalRunResult, PublicationResult]:
        raise RuntimeError("forced stage2 failure")

    return execute


@pytest.fixture
def harness_env(tmp_path: Path) -> dict[str, Path]:
    data_dir = tmp_path / "data"
    approved = tmp_path / "approved"
    approved.mkdir()
    data_dir.mkdir()
    _write_approved_document(approved)
    config_path = _write_config(tmp_path / "configs" / "execution.yaml")
    static = tmp_path / "static"
    static.mkdir()
    (static / "review.js").write_text("export {}", encoding="utf-8")
    (static / "review.css").write_text(".bl-review{}", encoding="utf-8")
    return {
        "data_dir": data_dir,
        "approved": approved,
        "config_path": config_path,
        "static": static,
    }


def _argv(env: dict[str, Path], *extra: str) -> list[str]:
    return [
        "--data-dir",
        str(env["data_dir"]),
        "--approved-documents-root",
        str(env["approved"]),
        *extra,
    ]


def _stub_assets(static: Path) -> Callable[[Path | None], tuple[Path, Path]]:
    def find_built_assets(static_dir: Path | None = None) -> tuple[Path, Path]:
        del static_dir
        return static / "review.js", static / "review.css"

    return find_built_assets


def _noop_serve(app: FastAPI, *, host: str, port: int) -> None:
    del app, host, port


def test_run_extraction_requires_config_job_and_revision() -> None:
    args = parser().parse_args(["--run-extraction"])
    assert missing_run_extraction_args(args) == (
        "--config",
        "--job-id",
        "--review-revision-id",
    )

    def refuse_create_app(*, data_dir: Path, approved_documents_root: Path) -> FastAPI:
        del data_dir, approved_documents_root
        return FastAPI()

    def refuse_extraction(**_kwargs: object) -> LocalLexicalJob:
        raise AssertionError("extraction must not run when args are missing")

    code = main(
        ["--run-extraction", "--data-dir", "unused", "--approved-documents-root", "unused"],
        create_app_fn=refuse_create_app,
        serve=_noop_serve,
        run_extraction_fn=refuse_extraction,
    )
    assert code == 2

    partial = Namespace(
        run_extraction=True,
        config="cfg.yaml",
        job_id="job-1",
        review_revision_id=None,
    )
    assert missing_run_extraction_args(partial) == ("--review-revision-id",)


def test_successful_run_extraction_closes_service_then_creates_ui(
    harness_env: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, Path] = {}
    served: list[FastAPI] = []
    closed: list[bool] = []

    class TrackingService(LocalLexicalJobService):
        def close(self) -> None:
            super().close()
            closed.append(True)

    def factory(data_dir: Path) -> LocalLexicalJobService:
        return TrackingService(
            data_dir,
            execute_stage2=_success_executor(),
            clock=lambda: FIXED_NOW,
        )

    def create_app_fn(*, data_dir: Path, approved_documents_root: Path) -> FastAPI:
        created["data_dir"] = data_dir
        created["approved"] = approved_documents_root
        return create_app(
            data_dir=data_dir,
            approved_documents_root=approved_documents_root,
            static_dir=harness_env["static"],
        )

    def serve(app: FastAPI, *, host: str, port: int) -> None:
        served.append(app)
        assert host == "127.0.0.1"
        assert port == 8767

    def run_extraction(
        *,
        data_dir: Path,
        approved_documents_root: Path,
        job_id: str,
        review_revision_id: str,
        config_path: Path,
        action: ExtractionReviewAction,
        **_unused: object,
    ) -> LocalLexicalJob:
        return run_extraction_job(
            data_dir=data_dir,
            approved_documents_root=approved_documents_root,
            job_id=job_id,
            review_revision_id=review_revision_id,
            config_path=config_path,
            action=action,
            service_factory=factory,
            timeout_seconds=5.0,
            poll_interval_seconds=0.01,
        )

    monkeypatch.setattr(
        "tests.extraction_review.local_harness.find_built_assets",
        _stub_assets(harness_env["static"]),
    )

    code = main(
        _argv(
            harness_env,
            "--job-id",
            DOC_JOB,
            "--review-revision-id",
            REVISION,
            "--config",
            str(harness_env["config_path"]),
            "--action",
            "materials_with_quantities",
            "--run-extraction",
        ),
        create_app_fn=create_app_fn,
        serve=serve,
        run_extraction_fn=run_extraction,
    )

    assert code == 0
    assert closed == [True]
    assert created["data_dir"] == harness_env["data_dir"].resolve()
    assert created["approved"] == harness_env["approved"].resolve()
    assert len(served) == 1
    client = TestClient(served[0])
    listed = client.get("/api/v1/extraction-reviews/jobs")
    assert listed.status_code == 200
    jobs = listed.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == DOC_JOB
    assert jobs[0]["action"] == ExtractionReviewAction.EXTRACT_MATERIALS.value


def test_failed_interrupted_and_timeout_do_not_start_ui(
    harness_env: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "tests.extraction_review.local_harness.find_built_assets",
        _stub_assets(harness_env["static"]),
    )
    ui_started = {"count": 0}

    def serve(app: FastAPI, *, host: str, port: int) -> None:
        del app, host, port
        ui_started["count"] += 1

    def refuse_create_app(*, data_dir: Path, approved_documents_root: Path) -> FastAPI:
        del data_dir, approved_documents_root
        return FastAPI()

    def fail_run(**_kwargs: object) -> LocalLexicalJob:
        return run_extraction_job(
            data_dir=harness_env["data_dir"],
            approved_documents_root=harness_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=harness_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
            service_factory=lambda data_dir: LocalLexicalJobService(
                data_dir,
                execute_stage2=_fail_executor(),
                clock=lambda: FIXED_NOW,
            ),
            timeout_seconds=5.0,
            poll_interval_seconds=0.01,
        )

    fail_code = main(
        _argv(
            harness_env,
            "--job-id",
            DOC_JOB,
            "--review-revision-id",
            REVISION,
            "--config",
            str(harness_env["config_path"]),
            "--run-extraction",
        ),
        create_app_fn=refuse_create_app,
        serve=serve,
        run_extraction_fn=fail_run,
    )
    assert fail_code == 1
    assert ui_started["count"] == 0

    def interrupted_job(**_kwargs: object) -> LocalLexicalJob:
        return LocalLexicalJob(
            local_job_id="11111111-1111-4111-8111-111111111111",
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            action=ExtractionReviewAction.EXTRACT_ALL,
            status=LocalJobStatus.INTERRUPTED,
            phase=LocalJobPhase.INTERRUPTED,
            submitted_at=FIXED_NOW,
            finished_at=FIXED_NOW,
            error=SafeStructuredError(
                code="INTERRUPTED",
                message="interrupted",
                retryable=False,
            ),
        )

    interrupted_code = main(
        _argv(
            harness_env,
            "--job-id",
            DOC_JOB,
            "--review-revision-id",
            REVISION,
            "--config",
            str(harness_env["config_path"]),
            "--run-extraction",
        ),
        create_app_fn=refuse_create_app,
        serve=serve,
        run_extraction_fn=interrupted_job,
    )
    assert interrupted_code == 1
    assert ui_started["count"] == 0

    def timeout_job(**_kwargs: object) -> LocalLexicalJob:
        raise TimeoutError("local lexical job timed out")

    timeout_code = main(
        _argv(
            harness_env,
            "--job-id",
            DOC_JOB,
            "--review-revision-id",
            REVISION,
            "--config",
            str(harness_env["config_path"]),
            "--run-extraction",
        ),
        create_app_fn=refuse_create_app,
        serve=serve,
        run_extraction_fn=timeout_job,
    )
    assert timeout_code == 1
    assert ui_started["count"] == 0


def test_without_run_extraction_opens_existing_completed_jobs(
    harness_env: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with LocalLexicalJobService(
        harness_env["data_dir"],
        execute_stage2=_success_executor(),
        clock=lambda: FIXED_NOW,
    ) as service:
        submitted = service.submit(
            approved_documents_root=harness_env["approved"],
            job_id=DOC_JOB,
            review_revision_id=REVISION,
            config_path=harness_env["config_path"],
            action=ExtractionReviewAction.EXTRACT_MATERIALS,
        )
        _wait_for(
            lambda: service.get_job(submitted.local_job_id).status is LocalJobStatus.COMPLETED
        )

    served: list[FastAPI] = []
    extraction_calls = {"count": 0}

    def create_app_fn(*, data_dir: Path, approved_documents_root: Path) -> FastAPI:
        return create_app(
            data_dir=data_dir,
            approved_documents_root=approved_documents_root,
            static_dir=harness_env["static"],
        )

    def serve(app: FastAPI, *, host: str, port: int) -> None:
        del host, port
        served.append(app)

    def must_not_extract(**_kwargs: object) -> LocalLexicalJob:
        extraction_calls["count"] += 1
        raise AssertionError("--run-extraction was absent")

    monkeypatch.setattr(
        "tests.extraction_review.local_harness.find_built_assets",
        _stub_assets(harness_env["static"]),
    )

    code = main(
        _argv(harness_env, "--port", "8767"),
        create_app_fn=create_app_fn,
        serve=serve,
        run_extraction_fn=must_not_extract,
    )
    assert code == 0
    assert extraction_calls["count"] == 0
    assert len(served) == 1
    client = TestClient(served[0])
    listed = client.get("/api/v1/extraction-reviews/jobs")
    assert listed.status_code == 200
    assert listed.json()["jobs"][0]["local_job_id"] == submitted.local_job_id
    page = client.get("/documents/local-extraction-review")
    assert page.status_code == 200
    assert 'id="extraction-review"' in page.text


def test_built_bundle_exports_review_and_extraction_mounts() -> None:
    from tests.extraction_review import local_harness as harness

    review_js = harness.REPO_ROOT / "src/app/document_review/static/review.js"
    assert review_js.is_file(), "run npm --prefix frontend run build before this check"
    text = review_js.read_text(encoding="utf-8")
    assert "mountReviewWorkspace" in text
    assert "mountExtractionReviewWorkspace" in text
    source = Path(harness.__file__).read_text(encoding="utf-8")
    assert "mountExtractionReviewWorkspace" in source
    assert "from '/documents/review-assets/review.js'" in source

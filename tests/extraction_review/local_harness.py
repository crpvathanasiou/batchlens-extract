"""Localhost Stage 3/4 extraction-review screen.

Serves the real Vue workspace and extraction-review API against a caller-supplied
data directory and approved-documents root. With ``--run-extraction``, first
submits one U2.2 lexical job for the selected approved document, waits for a
terminal status, then starts the same UI. Optional ``--config`` also wires the
in-workspace classified Extract All path. Identity is the synthetic
``local-test-reviewer``. Binds to 127.0.0.1. Does not mock the review UI.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.extraction_reviews import mount_extraction_review
from app.extraction_review.approved_documents import (
    ApprovedDocumentError,
    ApprovedDocumentsRegistry,
)
from app.extraction_review.contracts import ExtractionReviewAction
from app.extraction_review.local_jobs import (
    LocalJobStatus,
    LocalLexicalJob,
    LocalLexicalJobService,
    LocalLexicalJobServiceBusyError,
)
from app.extraction_review.stage4_local import LocalStage4Adapter, build_local_stage4_adapter
from app.extraction_review.workspace import LOCAL_REVIEW_ACTOR, ExtractionReviewWorkspace

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = Path(".local-extraction-review-data")
DEFAULT_APPROVED_ROOT = Path("approved-documents")
LABEL = "Local extraction review"
DEFAULT_EXTRACTION_TIMEOUT_SECONDS = 3600.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.5
DEFAULT_CLOSE_WAIT_SECONDS = 30.0

_ACTION_CHOICES: dict[str, ExtractionReviewAction] = {
    "full": ExtractionReviewAction.EXTRACT_ALL,
    "unit_operations_with_steps": ExtractionReviewAction.EXTRACT_UNIT_OPERATIONS,
    "materials_with_quantities": ExtractionReviewAction.EXTRACT_MATERIALS,
    "equipment_with_parameters": ExtractionReviewAction.EXTRACT_EQUIPMENT,
}
_TERMINAL_STATUSES = frozenset(
    {
        LocalJobStatus.COMPLETED,
        LocalJobStatus.FAILED,
        LocalJobStatus.INTERRUPTED,
    }
)


class LocalHarnessError(RuntimeError):
    """The extraction-review harness cannot start."""


class LocalDocumentHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        prefixes = ("/documents", "/api/v1/extraction-reviews")
        if scope["type"] != "http" or not str(path).startswith(prefixes):
            await self.app(scope, receive, send)
            return

        async def headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; style-src 'self'; "
                        b"connect-src 'self'; img-src 'self' data:; font-src 'self'; "
                        b"frame-ancestors 'none'; object-src 'none'; base-uri 'none'; "
                        b"form-action 'self'",
                    ),
                ]
            await send(message)

        await self.app(scope, receive, headers)


def find_built_assets(static: Path | None = None) -> tuple[Path, Path]:
    directory = (static or (REPO_ROOT / "src/app/document_review/static")).resolve()
    review_js = directory / "review.js"
    review_css = directory / "review.css"
    if not review_js.is_file() or not review_css.is_file():
        raise LocalHarnessError(
            "REVIEW_BUILD_MISSING: review.js and review.css are required.\n"
            "Run exactly:\n"
            "  npm --prefix frontend ci\n"
            "  npm --prefix frontend run build"
        )
    return review_js, review_css


def _safe_asset(static: Path, asset: str) -> Path | None:
    requested = (static / asset).resolve()
    try:
        requested.relative_to(static)
    except ValueError:
        return None
    return requested if requested.is_file() else None


def _page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Local extraction review</title>
  <link rel="stylesheet" href="/documents/review-assets/review.css">
</head>
<body>
  <div id="extraction-review"></div>
  <script type="module" src="/documents/local-extraction-review/bootstrap.js"></script>
</body>
</html>
"""


def _bootstrap(*, initial_local_job_id: str | None = None) -> str:
    option_lines = [f"  demoLabel: {LABEL!r}"]
    if initial_local_job_id is not None:
        option_lines.append(f"  initialLocalJobId: {initial_local_job_id!r}")
    options = ",\n".join(option_lines)
    script = (
        "import { mountExtractionReviewWorkspace } "
        "from '/documents/review-assets/review.js';\n"
        "const host = mountExtractionReviewWorkspace('#extraction-review', {\n"
        f"{options}\n"
        "});\n"
        "window.addEventListener('pagehide', () => host.unmount(), { once: true });\n"
    )
    return script


def create_app(
    *,
    data_dir: Path,
    approved_documents_root: Path,
    static_dir: Path | None = None,
    initial_local_job_id: str | None = None,
    config_path: Path | None = None,
    stage4_adapter: LocalStage4Adapter | None = None,
    compose_stage4: bool = False,
) -> FastAPI:
    review_js, _css = find_built_assets(static_dir)
    static = review_js.parent
    app = FastAPI(title="BatchLens local extraction review")
    adapter = stage4_adapter
    if adapter is None and compose_stage4:
        adapter = build_local_stage4_adapter(
            data_dir=data_dir,
            approved_documents_root=approved_documents_root,
            config_path=config_path,
        )
    mount_extraction_review(
        app,
        ExtractionReviewWorkspace(data_dir, approved_documents_root, actor=LOCAL_REVIEW_ACTOR),
        stage4_adapter=adapter,
    )

    def _screen() -> HTMLResponse:
        return HTMLResponse(_page())

    def _bootstrap_route() -> Response:
        return Response(
            _bootstrap(initial_local_job_id=initial_local_job_id),
            media_type="text/javascript",
        )

    def _review_asset(asset: str) -> FileResponse:
        requested = _safe_asset(static, asset)
        if requested is None:
            raise HTTPException(status_code=404)
        return FileResponse(requested)

    app.add_api_route(
        "/documents/local-extraction-review",
        _screen,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/documents/local-extraction-review/bootstrap.js",
        _bootstrap_route,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/documents/review-assets/{asset:path}",
        _review_asset,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_middleware(LocalDocumentHeaders)
    return app


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Local extraction-review workspace")
    result.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    result.add_argument("--approved-documents-root", default=str(DEFAULT_APPROVED_ROOT))
    result.add_argument("--port", type=int, default=8767)
    result.add_argument("--job-id", default=None)
    result.add_argument("--review-revision-id", default=None)
    result.add_argument(
        "--config",
        default=None,
        help=(
            "Stage 2 execution YAML. Required with --run-extraction; also wires "
            "in-workspace classified Extract All when the UI starts"
        ),
    )
    result.add_argument(
        "--action",
        choices=sorted(_ACTION_CHOICES),
        default="full",
        help="Lexical extraction preset when --run-extraction is set (default: full)",
    )
    result.add_argument(
        "--run-extraction",
        action="store_true",
        help=(
            "Submit one U2.2 lexical job for the selected approved document, "
            "wait for a terminal status, then start the Stage 3 UI"
        ),
    )
    return result


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def action_from_cli(value: str) -> ExtractionReviewAction:
    try:
        return _ACTION_CHOICES[value]
    except KeyError as exc:
        raise LocalHarnessError(f"unsupported --action {value!r}") from exc


def missing_run_extraction_args(args: argparse.Namespace) -> tuple[str, ...]:
    missing: list[str] = []
    if not args.config:
        missing.append("--config")
    if not args.job_id:
        missing.append("--job-id")
    if not args.review_revision_id:
        missing.append("--review-revision-id")
    return tuple(missing)


def wait_for_terminal_job(
    service: LocalLexicalJobService,
    local_job_id: str,
    *,
    timeout_seconds: float = DEFAULT_EXTRACTION_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> LocalLexicalJob:
    deadline = monotonic() + timeout_seconds
    while True:
        job = service.get_job(local_job_id)
        if job.status in _TERMINAL_STATUSES:
            return job
        if monotonic() >= deadline:
            raise TimeoutError(
                f"local lexical job {local_job_id} did not reach a terminal status "
                f"within {timeout_seconds:g} seconds (last status={job.status.value})"
            )
        sleep(poll_interval_seconds)


def close_job_service(
    service: LocalLexicalJobService,
    *,
    timeout_seconds: float = DEFAULT_CLOSE_WAIT_SECONDS,
    poll_interval_seconds: float = 0.05,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    deadline = monotonic() + timeout_seconds
    while True:
        try:
            service.close()
            return
        except LocalLexicalJobServiceBusyError:
            if monotonic() >= deadline:
                raise
            sleep(poll_interval_seconds)


def run_extraction_job(
    *,
    data_dir: Path,
    approved_documents_root: Path,
    job_id: str,
    review_revision_id: str,
    config_path: Path,
    action: ExtractionReviewAction,
    fuzzy_enabled: bool = False,
    timeout_seconds: float = DEFAULT_EXTRACTION_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    service_factory: Callable[[Path], LocalLexicalJobService] = LocalLexicalJobService,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> LocalLexicalJob:
    if not config_path.is_file():
        raise LocalHarnessError(f"lexical config not found: {config_path}")

    try:
        ApprovedDocumentsRegistry(approved_documents_root).select(job_id, review_revision_id)
    except ApprovedDocumentError as error:
        raise LocalHarnessError(f"{error.code}: {error.message}") from error

    service = service_factory(data_dir)
    try:
        submitted = service.submit(
            approved_documents_root=approved_documents_root,
            job_id=job_id,
            review_revision_id=review_revision_id,
            config_path=config_path,
            action=action,
            fuzzy_enabled=fuzzy_enabled,
        )
        print(f"Submitted local lexical job: {submitted.local_job_id}")
        print(f"  status: {submitted.status.value}")
        job = wait_for_terminal_job(
            service,
            submitted.local_job_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            sleep=sleep,
            monotonic=monotonic,
        )
    except BaseException:
        try:
            close_job_service(
                service,
                sleep=sleep,
                monotonic=monotonic,
            )
        except Exception:
            pass
        raise

    close_job_service(service, sleep=sleep, monotonic=monotonic)
    return job


def serve_app(app: FastAPI, *, host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, workers=1)


def _print_ui_banner(
    *,
    data_dir: Path,
    approved: Path,
    url: str,
    local_job_id: str | None = None,
    config_path: Path | None = None,
) -> None:
    print("Local extraction review")
    print(f"  data-dir: {data_dir}")
    print(f"  approved-documents: {approved}")
    print(f"  reviewer: {LOCAL_REVIEW_ACTOR}")
    if config_path is not None:
        print(f"  config: {config_path}")
    if local_job_id is not None:
        print(f"  local-job-id: {local_job_id}")
    print(f"  URL: {url}")


def main(
    argv: Sequence[str] | None = None,
    *,
    create_app_fn: Callable[..., FastAPI] = create_app,
    serve: Callable[..., None] = serve_app,
    run_extraction_fn: Callable[..., LocalLexicalJob] = run_extraction_job,
) -> int:
    args = parser().parse_args(argv)
    data_dir = resolve_path(args.data_dir)
    approved = resolve_path(args.approved_documents_root)
    url = f"http://127.0.0.1:{args.port}/documents/local-extraction-review"
    local_job_id: str | None = None
    config_path: Path | None = resolve_path(args.config) if args.config else None

    if args.run_extraction:
        missing = missing_run_extraction_args(args)
        if missing:
            joined = ", ".join(missing)
            print(
                "Local extraction review did not start:\n" f"--run-extraction requires {joined}",
                file=sys.stderr,
            )
            return 2
        assert args.config is not None
        assert args.job_id is not None
        assert args.review_revision_id is not None
        assert config_path is not None
        try:
            job = run_extraction_fn(
                data_dir=data_dir,
                approved_documents_root=approved,
                job_id=args.job_id,
                review_revision_id=args.review_revision_id,
                config_path=config_path,
                action=action_from_cli(args.action),
            )
        except KeyboardInterrupt:
            print(
                "Local extraction review did not start:\n" "extraction interrupted by user",
                file=sys.stderr,
            )
            return 130
        except TimeoutError as error:
            print(f"Local extraction review did not start:\n{error}", file=sys.stderr)
            return 1
        except LocalHarnessError as error:
            print(f"Local extraction review did not start:\n{error}", file=sys.stderr)
            return 2
        except Exception as error:
            print(
                f"Local extraction review did not start:\n{error}",
                file=sys.stderr,
            )
            return 1

        if job.status is not LocalJobStatus.COMPLETED:
            detail = job.status.value
            if job.error is not None:
                detail = f"{job.status.value}: {job.error.code}: {job.error.message}"
            print(
                "Local extraction review did not start:\n"
                f"local lexical job {job.local_job_id} ended as {detail}",
                file=sys.stderr,
            )
            return 1
        local_job_id = job.local_job_id

    try:
        find_built_assets()
        stage4_adapter = build_local_stage4_adapter(
            data_dir=data_dir,
            approved_documents_root=approved,
            config_path=config_path,
        )
        app_kwargs: dict[str, object] = {
            "data_dir": data_dir,
            "approved_documents_root": approved,
            "stage4_adapter": stage4_adapter,
            "config_path": config_path,
        }
        if local_job_id is not None:
            app_kwargs["initial_local_job_id"] = local_job_id
        app = create_app_fn(**app_kwargs)
    except LocalHarnessError as error:
        print(f"Local extraction review did not start:\n{error}", file=sys.stderr)
        return 2

    _print_ui_banner(
        data_dir=data_dir,
        approved=approved,
        url=url,
        local_job_id=local_job_id,
        config_path=config_path,
    )
    serve(app, host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

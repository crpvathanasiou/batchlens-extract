"""Executable, persistent, test-only local document-review server.

Reuses production review routes, validation, mapping, exports, and the built
Vue bundle. Substitutes only identity (``local-test-reviewer``) and file-backed
storage. Binds to 127.0.0.1. Does not prove Cognito, DynamoDB conditionals, S3
versioning, or AWS deployment. Supplied PDF/JSON/HTML originals are never written.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.document_reviews import install_errors as install_review_errors
from app.api.document_reviews import router as review_router
from app.api.documents import install_errors as install_job_errors
from app.document_jobs.contracts import JobError
from app.document_review.service import ReviewService
from tests.document_review.local_store import (
    JOB_ID,
    OWNER,
    LocalHarnessError,
    LocalHeads,
    LocalJobs,
    LocalReviewStore,
)

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = Path("manual-input/source.pdf")
DEFAULT_DOCUMENT = Path("out/comparison/fexofenadine-textractor-20260916-173938/document.json")
DEFAULT_TEXTRACT = Path("out/comparison/fexofenadine-textractor-20260916-173938/textract.json")
DEFAULT_HTML = Path("out/comparison/fexofenadine-textractor-20260916-173938/document.html")
DEFAULT_DATA_DIR = Path(".local-review-data/fexofenadine")
TOKEN = "local-review-token"
LABEL = "Local demo · test reviewer"
LOCAL_CSS = """.local-demo-label {
  position: fixed; z-index: 10000; right: 12px; bottom: 12px; padding: 6px 10px;
  border-radius: 999px; background: #172033; color: white;
  font: 600 12px/1.2 system-ui, sans-serif;
}
html, body, #review { min-height: 100%; margin: 0; }
"""


class LocalDocumentHeaders:
    """Production-equivalent no-store and browser isolation, without production startup."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith(("/documents", "/api/v1/documents")):
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
                        b"connect-src 'self'; worker-src 'self'; img-src 'self' data:; "
                        b"font-src 'self'; frame-ancestors 'none'; object-src 'none'; "
                        b"base-uri 'none'; form-action 'self'",
                    ),
                ]
            await send(message)

        await self.app(scope, receive, headers)


class LocalAuth:
    """Accepts only the harness token and returns the synthetic owner. Not Cognito."""

    def verify(self, token: str) -> str:
        if token != TOKEN:
            raise JobError("UNAUTHORIZED", 401)
        return OWNER


def resolve_path(value: str | os.PathLike[str], root: Path = REPO_ROOT) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def _readable(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            stream.read(1)
    except OSError:
        return False
    return path.is_file()


def validate_inputs(paths: dict[str, Path]) -> None:
    missing = [(name, path) for name, path in paths.items() if not _readable(path)]
    if missing:
        details = "\n".join(f"  {name}: {path}" for name, path in missing)
        raise LocalHarnessError(f"UNREADABLE_LOCAL_INPUTS:\n{details}")


def find_built_assets(root: Path | None = None) -> tuple[Path, Path, Path]:
    static = (root or REPO_ROOT / "src/app/document_review/static").resolve()
    review_js = static / "review.js"
    review_css = static / "review.css"
    workers = sorted(
        path
        for pattern in ("**/pdf.worker*.mjs", "**/pdf.worker*.js")
        for path in static.glob(pattern)
        if path.is_file()
    )
    if not review_js.is_file() or not review_css.is_file() or not workers:
        raise LocalHarnessError(
            "REVIEW_BUILD_MISSING: review.js, review.css, and the PDF worker are required.\n"
            "Run exactly:\n"
            "  npm --prefix frontend ci\n"
            "  npm --prefix frontend run build"
        )
    return review_js, review_css, workers[0]


def _safe_asset(static: Path, asset: str) -> Path | None:
    requested = (static / asset).resolve()
    try:
        requested.relative_to(static)
    except ValueError:
        return None
    return requested if requested.is_file() else None


def _page(filename: str) -> str:
    escaped_filename = (
        filename.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Local document review</title>
  <link rel="stylesheet" href="/documents/review-assets/review.css">
  <link rel="stylesheet" href="/documents/local-review/bootstrap.css">
</head>
<body>
  <div id="review" data-filename="{escaped_filename}"></div>
  <div class="local-demo-label">{LABEL}</div>
  <script type="module" src="/documents/local-review/bootstrap.js"></script>
</body>
</html>
"""


def _bootstrap() -> str:
    return f"""import {{ mountReviewWorkspace }} from '/documents/review-assets/review.js';
const host = mountReviewWorkspace('#review', {{
  jobId: {JOB_ID!r},
  filename: document.querySelector('#review').dataset.filename,
  getAccessToken: () => {TOKEN!r},
  onAuthenticationRequired: () => {{}},
  onDirtyChange: () => {{}},
  onBack: () => {{}},
  localDemo: true,
  demoLabel: {LABEL!r}
}});
window.addEventListener('pagehide', () => host.unmount(), {{ once: true }});
"""


def create_app(
    *,
    source: Path,
    document: Path,
    textract: Path,
    html: Path,
    data_dir: Path,
    static_dir: Path | None = None,
) -> FastAPI:
    inputs = {
        "source": source.resolve(),
        "document": document.resolve(),
        "textract": textract.resolve(),
        "html": html.resolve(),
    }
    validate_inputs(inputs)
    review_js, _, _ = find_built_assets(static_dir)
    static = review_js.parent
    store = LocalReviewStore(
        data_dir.resolve(),
        inputs["source"],
        inputs["document"],
        inputs["textract"],
        inputs["html"],
    )
    service = ReviewService(LocalJobs(store), LocalHeads(store), store)

    app = FastAPI(title="BatchLens local review harness")
    app.state.document_review_service = service
    app.state.document_auth = LocalAuth()
    app.state.local_review_store = store
    app.include_router(review_router)
    install_job_errors(app)
    install_review_errors(app)

    def _local_review() -> HTMLResponse:
        return HTMLResponse(_page(store.job.filename))

    def _bootstrap_route() -> Response:
        return Response(_bootstrap(), media_type="text/javascript")

    def _bootstrap_css() -> Response:
        return Response(LOCAL_CSS, media_type="text/css")

    def _review_asset(asset: str) -> FileResponse:
        requested = _safe_asset(static, asset)
        if requested is None:
            raise JobError("REVIEW_BUILD_MISSING", 404)
        return FileResponse(requested)

    def _local_download(token: str) -> Response:
        result = store.download_bytes(token)
        if result is None:
            return JSONResponse({"code": "EXPORT_NOT_FOUND"}, status_code=404)
        body, artifact, filename = result
        safe = re.sub(r"[^A-Za-z0-9._() -]", "_", filename)[:180].strip(". ")
        return Response(
            body,
            media_type=artifact.content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{safe or "reviewed-document"}"'
            },
        )

    app.add_api_route(
        "/documents/local-review", _local_review, methods=["GET"], include_in_schema=False
    )
    app.add_api_route(
        "/documents/local-review/bootstrap.js",
        _bootstrap_route,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/documents/local-review/bootstrap.css",
        _bootstrap_css,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/documents/review-assets/{asset:path}",
        _review_asset,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/documents/local-review/downloads/{token}",
        _local_download,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_middleware(LocalDocumentHeaders)
    return app


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Persistent local document-review harness")
    result.add_argument("--source", default=str(DEFAULT_SOURCE))
    result.add_argument("--document", default=str(DEFAULT_DOCUMENT))
    result.add_argument("--textract", default=str(DEFAULT_TEXTRACT))
    result.add_argument("--html", default=str(DEFAULT_HTML))
    result.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    result.add_argument("--port", type=int, default=8765)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    inputs = {
        "source": resolve_path(args.source),
        "document": resolve_path(args.document),
        "textract": resolve_path(args.textract),
        "html": resolve_path(args.html),
    }
    data_dir = resolve_path(args.data_dir)
    try:
        validate_inputs(inputs)
        find_built_assets()
        app = create_app(**inputs, data_dir=data_dir)
    except (LocalHarnessError, OSError, ValueError) as error:
        print(f"Local review harness did not start:\n{error}", file=sys.stderr)
        return 2

    url = f"http://127.0.0.1:{args.port}/documents/local-review"
    print("Local document review harness")
    for name, path in inputs.items():
        print(f"  {name}: {path}")
    print(f"  data-dir: {data_dir}")
    print(f"  URL: {url}")
    print(f"  reviewer: {OWNER}")
    print("  originals: untouched (all generated state stays in data-dir)")
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

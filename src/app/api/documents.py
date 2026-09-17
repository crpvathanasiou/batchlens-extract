"""Authenticated document HTTP adapter. Synchronous routes run in FastAPI's thread pool."""

from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field

from app.document_conversion.aws import AwsError
from app.document_conversion.contracts import Model
from app.document_jobs.contracts import JobError, JobStatus, UploadGrant
from app.document_jobs.service import JobService
from app.document_jobs.settings import DocumentSettings

router = APIRouter()


class Verifier(Protocol):
    def verify(self, token: str) -> str: ...


class UploadRequest(Model):
    filename: str = Field(min_length=1, max_length=180)
    size_bytes: int = Field(ge=5, strict=True)


def service(request: Request) -> JobService:
    return cast(JobService, request.app.state.document_service)


def owner(request: Request, authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise JobError("UNAUTHORIZED", 401)
    verifier = cast(Verifier, request.app.state.document_auth)
    return verifier.verify(authorization[7:])


Service = Annotated[JobService, Depends(service)]
Owner = Annotated[str, Depends(owner)]


@router.post("/api/v1/documents/uploads", status_code=201)
def upload(body: UploadRequest, svc: Service, user: Owner) -> UploadGrant:
    return svc.initiate(user, body.filename, body.size_bytes)


@router.post("/api/v1/documents/jobs/{job_id}/start", status_code=202)
def start(job_id: str, svc: Service, user: Owner) -> JobStatus:
    return svc.start(job_id, user)


@router.get("/api/v1/documents/jobs/{job_id}")
def status(job_id: str, svc: Service, user: Owner) -> JobStatus:
    return JobStatus.from_job(svc.owned(job_id, user))


@router.get("/api/v1/documents/jobs")
def jobs(svc: Service, user: Owner) -> list[JobStatus]:
    # Dev-scale scan; keep the response bounded. No document content in job metadata.
    from heapq import nlargest

    recent = nlargest(100, svc.store.owned(user), key=lambda job: job.created_at)
    return [JobStatus.from_job(job) for job in recent]


@router.post("/api/v1/documents/jobs/{job_id}/retry", status_code=202)
def retry(job_id: str, svc: Service, user: Owner) -> JobStatus:
    return svc.retry(job_id, user)


@router.get("/api/v1/documents/jobs/{job_id}/artifacts/{name}")
def download(job_id: str, name: str, svc: Service, user: Owner) -> dict[str, str]:
    return {"url": svc.download(job_id, user, name)}


@router.get("/documents/config")
def config(request: Request) -> dict[str, str | int]:
    settings = cast(DocumentSettings, request.app.state.document_settings)
    return {
        "region": settings.region,
        "client_id": settings.cognito_client_id,
        "max_pdf_bytes": settings.max_pdf_bytes,
    }


@router.get("/documents/review-assets/{asset:path}", include_in_schema=False)
def review_asset(asset: str) -> FileResponse:
    from pathlib import Path

    root = (Path(__file__).parent.parent / "document_review" / "static").resolve()
    requested = (root / asset).resolve()
    if not requested.is_relative_to(root) or not requested.is_file():
        raise JobError("REVIEW_BUILD_MISSING", 404)
    return FileResponse(requested)


@router.get("/documents", include_in_schema=False)
@router.get("/documents/{asset}", include_in_schema=False)
def ui(asset: str = "index.html") -> FileResponse:
    from pathlib import Path

    if asset not in {"index.html", "app.js", "style.css"}:
        raise JobError("NOT_FOUND", 404)
    return FileResponse(Path(__file__).parent.parent / "document_jobs" / "static" / asset)


async def job_error_handler(request: Request, error: Exception) -> JSONResponse:
    if isinstance(error, JobError):
        return JSONResponse(
            {"code": error.code}, status_code=error.status, headers={"Cache-Control": "no-store"}
        )
    return JSONResponse(
        {"code": "AWS_REQUEST_FAILED"}, status_code=503, headers={"Cache-Control": "no-store"}
    )


def install_errors(app: object) -> None:
    # Kept out of use cases; concrete FastAPI composition owns registration.
    from fastapi import FastAPI

    if isinstance(app, FastAPI):
        app.add_exception_handler(JobError, job_error_handler)
        app.add_exception_handler(AwsError, job_error_handler)

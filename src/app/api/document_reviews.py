"""Synchronous authenticated document-review routes.

Every handler depends on ``owner`` from the documents API, so review access
uses the same ownership-hiding job lookup as conversion downloads.
"""

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.api.documents import Owner, owner
from app.document_review.contracts import (
    FinalApprovalBody,
    PageApprovalBody,
    ReviewError,
    ReviewState,
    UpdateReviewBody,
)
from app.document_review.service import ReviewService

router = APIRouter()


def service(request: Request) -> ReviewService:
    return cast(ReviewService, request.app.state.document_review_service)


Service = Annotated[ReviewService, Depends(service)]


@router.get("/api/v1/documents/jobs/{job_id}/review")
def get_review(job_id: str, svc: Service, user: Owner) -> ReviewState:
    return svc.get(job_id, user)


@router.put("/api/v1/documents/jobs/{job_id}/review")
def update_review(job_id: str, body: UpdateReviewBody, svc: Service, user: Owner) -> ReviewState:
    return svc.update(job_id, user, body)


@router.post("/api/v1/documents/jobs/{job_id}/review/pages/{page_number}/approve")
def approve_page(
    job_id: str,
    page_number: int,
    body: PageApprovalBody,
    svc: Service,
    user: Owner,
) -> ReviewState:
    return svc.approve_page(job_id, user, page_number, body)


@router.post("/api/v1/documents/jobs/{job_id}/review/approve")
def approve_review(job_id: str, body: FinalApprovalBody, svc: Service, user: Owner) -> ReviewState:
    return svc.approve(job_id, user, body)


@router.get("/api/v1/documents/jobs/{job_id}/review/revisions/{revision_id}/exports/{format}")
def export_review(
    job_id: str,
    revision_id: str,
    format: Literal["html", "json"],
    svc: Service,
    user: Owner,
) -> dict[str, str]:
    return {"url": svc.export(job_id, user, revision_id, format)}


@router.get("/api/v1/documents/jobs/{job_id}/source")
@router.get("/api/v1/documents/jobs/{job_id}/review/source", include_in_schema=False)
def source(job_id: str, svc: Service, user: Owner) -> StreamingResponse:
    stream, filename = svc.source(job_id, user)
    return StreamingResponse(
        stream,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


async def review_error_handler(request: Request, error: Exception) -> JSONResponse:
    if isinstance(error, ReviewError):
        return JSONResponse(
            {"code": error.code}, status_code=error.status, headers={"Cache-Control": "no-store"}
        )
    return JSONResponse(
        {"code": "REVIEW_REQUEST_FAILED"},
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


async def validation_error_handler(request: Request, error: Exception) -> Response:
    if "/review" not in request.url.path:
        return await request_validation_exception_handler(
            request, cast(RequestValidationError, error)
        )
    return JSONResponse(
        {"code": "INVALID_REVIEW"},
        status_code=422,
        headers={"Cache-Control": "no-store"},
    )


def install_errors(app: object) -> None:
    from fastapi import FastAPI

    if isinstance(app, FastAPI):
        app.add_exception_handler(ReviewError, review_error_handler)
        app.add_exception_handler(RequestValidationError, validation_error_handler)


__all__ = ["install_errors", "owner", "router"]

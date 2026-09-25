"""Synchronous authenticated document-review routes.

Every handler depends on ``owner`` from the documents API, so review access
uses the same ownership-hiding job lookup as conversion downloads.
"""

import re
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, Path, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.api.documents import Owner, owner
from app.document_review.contracts import (
    FINGERPRINT_PATTERN,
    REVIEW_CONTEXT_HEADER,
    REVISION_PATTERN,
    FinalApprovalBody,
    OperationLookup,
    PageApprovalBody,
    ReviewContext,
    ReviewError,
    ReviewState,
    UpdateReviewBody,
)
from app.document_review.service import ReviewService

router = APIRouter()
_CONTEXT_ID = re.compile(FINGERPRINT_PATTERN)


def service(request: Request) -> ReviewService:
    return cast(ReviewService, request.app.state.document_review_service)


Service = Annotated[ReviewService, Depends(service)]
ContextHeader = Annotated[str | None, Header(alias=REVIEW_CONTEXT_HEADER)]


def _no_store(model: ReviewContext | OperationLookup | ReviewState) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


def _parsed_context_header(value: str | None, *, required: bool) -> str | None:
    if value is None or value == "":
        if required:
            raise ReviewError("INVALID_REVIEW", 422)
        return None
    if _CONTEXT_ID.fullmatch(value) is None:
        raise ReviewError("INVALID_REVIEW", 422)
    return value


def _guard_context(
    svc: ReviewService, job_id: str, user: str, header: str | None, *, required: bool
) -> None:
    context_id = _parsed_context_header(header, required=required)
    if context_id is not None:
        svc.require_matching_context(job_id, user, context_id)


@router.get("/api/v1/documents/jobs/{job_id}/review")
def get_review(job_id: str, svc: Service, user: Owner) -> ReviewState:
    return svc.get(job_id, user)


@router.get("/api/v1/documents/jobs/{job_id}/review/context")
def get_review_context(job_id: str, svc: Service, user: Owner) -> JSONResponse:
    return _no_store(svc.review_context(job_id, user))


@router.get("/api/v1/documents/jobs/{job_id}/review/operations/{operation_id}")
def lookup_save_operation(
    job_id: str,
    svc: Service,
    user: Owner,
    x_review_context: ContextHeader,
    operation_id: Annotated[str, Path(pattern=REVISION_PATTERN)],
) -> JSONResponse:
    _guard_context(svc, job_id, user, x_review_context, required=True)
    return _no_store(
        OperationLookup(
            context=svc.review_context(job_id, user),
            reconciliation=svc.reconcile_save_operation(job_id, user, operation_id),
        )
    )


@router.put("/api/v1/documents/jobs/{job_id}/review")
def update_review(
    job_id: str,
    body: UpdateReviewBody,
    svc: Service,
    user: Owner,
    x_review_context: ContextHeader = None,
) -> ReviewState:
    _guard_context(svc, job_id, user, x_review_context, required=False)
    return svc.update(job_id, user, body)


@router.post("/api/v1/documents/jobs/{job_id}/review/pages/{page_number}/approve")
def approve_page(
    job_id: str,
    page_number: int,
    body: PageApprovalBody,
    svc: Service,
    user: Owner,
    x_review_context: ContextHeader = None,
) -> ReviewState:
    _guard_context(svc, job_id, user, x_review_context, required=False)
    return svc.approve_page(job_id, user, page_number, body)


@router.post("/api/v1/documents/jobs/{job_id}/review/approve")
def approve_review(
    job_id: str,
    body: FinalApprovalBody,
    svc: Service,
    user: Owner,
    x_review_context: ContextHeader = None,
) -> ReviewState:
    _guard_context(svc, job_id, user, x_review_context, required=False)
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

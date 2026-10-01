"""Local Stage 3/4 extraction-review HTTP surface.

Lists completed lexical jobs, opens one current review, saves page-scoped edits,
and approves the saved extraction result. Local Stage 4 adds approved-document
selection, page classification, and classified Extract All against the same
harness-mounted surface. There is no page, finding, or revision history route.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.extraction_review.contracts import (
    MAX_FINDING_DISPLAY_TEXT,
    MAX_FINDING_EDITS_PER_SAVE,
    Component,
    ExtractionReviewState,
    LexicalFindingOrigin,
    ReviewFindingRecord,
)
from app.extraction_review.local_jobs import LocalLexicalJob
from app.extraction_review.stage4_local import (
    ClassificationStateView,
    ExtractAllNoEligibleView,
    ExtractAllSubmittedView,
    LocalStage4Adapter,
)
from app.extraction_review.workspace import (
    AddPageEdit,
    ExtractionReviewWorkspace,
    ExtractionWorkspaceError,
    PatchPageEdit,
    RemovePageEdit,
    ReplacePageEdit,
    RestorePageEdit,
    finding_page_number,
)

router = APIRouter()


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompletedJobResponse(ExtractionResponse):
    local_job_id: str
    job_id: str
    review_revision_id: str
    action: str
    extraction_overall: str
    finished_at: datetime | None = None


class CompletedJobListResponse(ExtractionResponse):
    jobs: tuple[CompletedJobResponse, ...]


class FindingResponse(ExtractionResponse):
    finding_id: str
    component: str | None
    display_text: str | None
    page_number: int | None
    evidence_status: str | None
    removed: bool
    origin_kind: Literal["lexical", "user_added"]
    block_node_id: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    original_matched_text: str | None = None
    added_by_user: bool
    changed_by_user: bool
    removed_by_user: bool


class OpenedReviewResponse(ExtractionResponse):
    local_job_id: str
    job_id: str
    review_revision_id: str
    action: str
    extraction_overall: str
    current_revision_id: str
    approval_state: Literal["not_approved", "approved"]
    pages: tuple[int, ...]
    findings: tuple[FindingResponse, ...]
    classification: ClassificationStateView | None = None


class ReviewedPageResponse(ExtractionResponse):
    page_number: int
    html: str


class ApprovedDocumentResponse(ExtractionResponse):
    job_id: str
    review_revision_id: str


class ApprovedDocumentListResponse(ExtractionResponse):
    documents: tuple[ApprovedDocumentResponse, ...]


class ApprovedDocumentPagesResponse(ExtractionResponse):
    job_id: str
    review_revision_id: str
    pages: tuple[int, ...]


class ClassificationEnvelopeResponse(ExtractionResponse):
    classification: ClassificationStateView | None = None


class LexicalJobStatusResponse(ExtractionResponse):
    local_job_id: str
    job_id: str
    review_revision_id: str
    status: str
    phase: str
    action: str
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    classified: bool
    selected_page_numbers: tuple[int, ...] | None = None
    extraction_overall: str | None = None
    reviewable: bool


class ExtractAllSubmittedResponse(ExtractionResponse):
    kind: Literal["submitted"] = "submitted"
    job: LexicalJobStatusResponse


class ExtractAllNoEligibleResponse(ExtractionResponse):
    kind: Literal["no_eligible_pages"] = "no_eligible_pages"
    message: str


class AddEditBody(ExtractionResponse):
    op: Literal["add"]
    finding_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    component: Component
    display_text: str = Field(min_length=1, max_length=MAX_FINDING_DISPLAY_TEXT)


class PatchEditBody(ExtractionResponse):
    op: Literal["patch_text"]
    finding_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    display_text: str = Field(min_length=1, max_length=MAX_FINDING_DISPLAY_TEXT)


class ReplaceEditBody(ExtractionResponse):
    op: Literal["replace"]
    finding_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    component: Component
    display_text: str = Field(min_length=1, max_length=MAX_FINDING_DISPLAY_TEXT)


class RemoveEditBody(ExtractionResponse):
    op: Literal["remove"]
    finding_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    note: str | None = None


class RestoreEditBody(ExtractionResponse):
    op: Literal["restore"]
    finding_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)


EditBody = Annotated[
    AddEditBody | PatchEditBody | ReplaceEditBody | RemoveEditBody | RestoreEditBody,
    Field(discriminator="op"),
]


class SaveExtractionReviewBody(ExtractionResponse):
    expected_revision_id: str = Field(min_length=1)
    edits: list[EditBody] = Field(max_length=MAX_FINDING_EDITS_PER_SAVE)


class ApproveExtractionReviewBody(ExtractionResponse):
    expected_revision_id: str = Field(min_length=1)


def workspace(request: Request) -> ExtractionReviewWorkspace:
    return cast(ExtractionReviewWorkspace, request.app.state.extraction_review_workspace)


def stage4_optional(request: Request) -> LocalStage4Adapter | None:
    adapter = getattr(request.app.state, "extraction_review_stage4", None)
    if adapter is None:
        return None
    return cast(LocalStage4Adapter, adapter)


def stage4_required(request: Request) -> LocalStage4Adapter:
    adapter = stage4_optional(request)
    if adapter is None:
        raise ExtractionWorkspaceError(
            "STAGE4_UNAVAILABLE",
            "local Stage 4 actions are not configured for this workspace",
            503,
        )
    return adapter


Workspace = Annotated[ExtractionReviewWorkspace, Depends(workspace)]
Stage4 = Annotated[LocalStage4Adapter, Depends(stage4_required)]
OptionalStage4 = Annotated[LocalStage4Adapter | None, Depends(stage4_optional)]


def mount_extraction_review(
    app: FastAPI,
    review_workspace: ExtractionReviewWorkspace,
    *,
    stage4_adapter: LocalStage4Adapter | None = None,
) -> None:
    app.state.extraction_review_workspace = review_workspace
    app.state.extraction_review_stage4 = stage4_adapter
    app.include_router(router)
    install_errors(app)


@router.get("/api/v1/extraction-reviews/jobs")
def list_jobs(review: Workspace) -> JSONResponse:
    return _json(
        CompletedJobListResponse(
            jobs=tuple(_job_response(job) for job in review.list_completed_jobs())
        )
    )


@router.get("/api/v1/extraction-reviews/jobs/{local_job_id}")
def open_job(
    local_job_id: str,
    review: Workspace,
    stage4_api: OptionalStage4,
) -> JSONResponse:
    job, state, pages = review.open_job(local_job_id)
    return _json(_opened(job, state, pages, stage4_api=stage4_api))


@router.get("/api/v1/extraction-reviews/jobs/{local_job_id}/pages/{page_number}")
def reviewed_page(local_job_id: str, page_number: int, review: Workspace) -> JSONResponse:
    html = review.page_html(local_job_id, page_number)
    return _json(ReviewedPageResponse(page_number=page_number, html=html))


@router.put("/api/v1/extraction-reviews/jobs/{local_job_id}")
def save_review(
    local_job_id: str,
    body: SaveExtractionReviewBody,
    review: Workspace,
    stage4_api: OptionalStage4,
) -> JSONResponse:
    classification = _prevalidate_job_classification(local_job_id, stage4_api)
    state = review.save_page_edits(
        local_job_id,
        expected_revision_id=body.expected_revision_id,
        edits=tuple(_page_edit(edit) for edit in body.edits),
    )
    job, _, pages = review.open_job(local_job_id)
    return _json(_opened(job, state, pages, classification=classification))


@router.post("/api/v1/extraction-reviews/jobs/{local_job_id}/approve")
def approve_review(
    local_job_id: str,
    body: ApproveExtractionReviewBody,
    review: Workspace,
    stage4_api: OptionalStage4,
) -> JSONResponse:
    classification = _prevalidate_job_classification(local_job_id, stage4_api)
    state = review.approve_saved_result(
        local_job_id,
        expected_revision_id=body.expected_revision_id,
    )
    job, _, pages = review.open_job(local_job_id)
    return _json(_opened(job, state, pages, classification=classification))


@router.get("/api/v1/extraction-reviews/approved-documents")
def list_approved_documents(stage4_api: Stage4) -> JSONResponse:
    documents = stage4_api.list_approved_documents()
    return _json(
        ApprovedDocumentListResponse(
            documents=tuple(
                ApprovedDocumentResponse(
                    job_id=item.job_id,
                    review_revision_id=item.review_revision_id,
                )
                for item in documents
            )
        )
    )


@router.get("/api/v1/extraction-reviews/approved-documents/{job_id}/{review_revision_id}/pages")
def approved_document_pages(
    job_id: str,
    review_revision_id: str,
    stage4_api: Stage4,
) -> JSONResponse:
    view = stage4_api.document_pages(job_id, review_revision_id)
    return _json(
        ApprovedDocumentPagesResponse(
            job_id=view.job_id,
            review_revision_id=view.review_revision_id,
            pages=view.pages,
        )
    )


@router.get(
    "/api/v1/extraction-reviews/approved-documents/{job_id}/{review_revision_id}/pages/{page_number}"
)
def approved_document_page_html(
    job_id: str,
    review_revision_id: str,
    page_number: int,
    stage4_api: Stage4,
) -> JSONResponse:
    html = stage4_api.approved_page_html(job_id, review_revision_id, page_number)
    return _json(ReviewedPageResponse(page_number=page_number, html=html))


@router.get(
    "/api/v1/extraction-reviews/approved-documents/{job_id}/{review_revision_id}/classification"
)
def get_document_classification(
    job_id: str,
    review_revision_id: str,
    stage4_api: Stage4,
) -> JSONResponse:
    classification = stage4_api.get_current_classification(job_id, review_revision_id)
    return _json(ClassificationEnvelopeResponse(classification=classification))


@router.post("/api/v1/extraction-reviews/approved-documents/{job_id}/{review_revision_id}/classify")
def start_document_classification(
    job_id: str,
    review_revision_id: str,
    stage4_api: Stage4,
) -> JSONResponse:
    classification = stage4_api.start_classification(job_id, review_revision_id)
    return _json(ClassificationEnvelopeResponse(classification=classification))


@router.post(
    "/api/v1/extraction-reviews/approved-documents/{job_id}/{review_revision_id}/extract-all"
)
def extract_all_classified(
    job_id: str,
    review_revision_id: str,
    stage4_api: Stage4,
) -> JSONResponse:
    result = stage4_api.extract_all(job_id, review_revision_id)
    if isinstance(result, ExtractAllNoEligibleView):
        return _json(ExtractAllNoEligibleResponse(message=result.message))
    assert isinstance(result, ExtractAllSubmittedView)
    return _json(ExtractAllSubmittedResponse(job=_lexical_status_response(result.job)))


@router.get("/api/v1/extraction-reviews/local-jobs/{local_job_id}")
def local_job_status(local_job_id: str, stage4_api: Stage4) -> JSONResponse:
    status = stage4_api.lexical_job_status(local_job_id)
    return _json(_lexical_status_response(status))


@router.get("/api/v1/extraction-reviews/jobs/{local_job_id}/classification")
def job_classification_snapshot(local_job_id: str, stage4_api: Stage4) -> JSONResponse:
    classification = stage4_api.classification_for_local_job(local_job_id)
    return _json(ClassificationEnvelopeResponse(classification=classification))


@router.get("/api/v1/extraction-reviews/jobs/{local_job_id}/results.txt")
def download_results_txt(local_job_id: str, review: Workspace) -> PlainTextResponse:
    text = review.results_txt(local_job_id)
    filename = f"extraction-results-{local_job_id}.txt"
    return PlainTextResponse(
        text,
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def _page_edit(
    edit: AddEditBody | PatchEditBody | ReplaceEditBody | RemoveEditBody | RestoreEditBody,
) -> AddPageEdit | PatchPageEdit | ReplacePageEdit | RemovePageEdit | RestorePageEdit:
    if isinstance(edit, AddEditBody):
        return AddPageEdit(
            finding_id=edit.finding_id,
            page_number=edit.page_number,
            component=edit.component,
            display_text=edit.display_text,
        )
    if isinstance(edit, PatchEditBody):
        return PatchPageEdit(
            finding_id=edit.finding_id,
            page_number=edit.page_number,
            display_text=edit.display_text,
        )
    if isinstance(edit, ReplaceEditBody):
        return ReplacePageEdit(
            finding_id=edit.finding_id,
            page_number=edit.page_number,
            component=edit.component,
            display_text=edit.display_text,
        )
    if isinstance(edit, RestoreEditBody):
        return RestorePageEdit(finding_id=edit.finding_id, page_number=edit.page_number)
    return RemovePageEdit(finding_id=edit.finding_id, page_number=edit.page_number, note=edit.note)


def _job_response(job: LocalLexicalJob) -> CompletedJobResponse:
    overall = "unknown"
    if job.extraction is not None:
        overall = job.extraction.overall.value
    return CompletedJobResponse(
        local_job_id=job.local_job_id,
        job_id=job.job_id,
        review_revision_id=job.review_revision_id,
        action=job.action.value,
        extraction_overall=overall,
        finished_at=job.finished_at,
    )


def _prevalidate_job_classification(
    local_job_id: str,
    stage4_api: LocalStage4Adapter | None,
) -> ClassificationStateView | None:
    """Validate a classified job snapshot before Stage 3 mutation, if applicable.

    Legacy/unclassified jobs return ``None`` without inventing classifier data.
    Classified jobs fail closed on missing/malformed/mismatched snapshots.
    """

    if stage4_api is None:
        return None
    return stage4_api.classification_for_local_job(local_job_id)


def _opened(
    job: LocalLexicalJob,
    state: ExtractionReviewState,
    pages: tuple[int, ...],
    *,
    stage4_api: LocalStage4Adapter | None = None,
    classification: ClassificationStateView | None = None,
) -> OpenedReviewResponse:
    summary = _job_response(job)
    resolved = classification
    if resolved is None and stage4_api is not None and job.classified_extraction is not None:
        resolved = stage4_api.classification_for_local_job(job.local_job_id)
    return OpenedReviewResponse(
        local_job_id=summary.local_job_id,
        job_id=summary.job_id,
        review_revision_id=summary.review_revision_id,
        action=summary.action,
        extraction_overall=summary.extraction_overall,
        current_revision_id=state.current_revision_id,
        approval_state=state.approval_state.value,
        pages=pages,
        findings=tuple(_finding_response(finding) for finding in state.findings),
        classification=resolved,
    )


def _lexical_status_response(status: object) -> LexicalJobStatusResponse:
    from app.extraction_review.stage4_local import LexicalJobStatusView

    view = cast(LexicalJobStatusView, status)
    return LexicalJobStatusResponse(
        local_job_id=view.local_job_id,
        job_id=view.job_id,
        review_revision_id=view.review_revision_id,
        status=view.status,
        phase=view.phase,
        action=view.action,
        submitted_at=view.submitted_at,
        started_at=view.started_at,
        finished_at=view.finished_at,
        error_code=view.error_code,
        error_message=view.error_message,
        classified=view.classified,
        selected_page_numbers=view.selected_page_numbers,
        extraction_overall=view.extraction_overall,
        reviewable=view.reviewable,
    )


def _finding_response(finding: ReviewFindingRecord) -> FindingResponse:
    current = finding.current
    origin = finding.origin
    block_node_id = None
    start_char = None
    end_char = None
    original = None
    if isinstance(origin, LexicalFindingOrigin):
        original = origin.original_matched_text
        block_node_id = origin.evidence.block_node_id
        if origin.evidence.location is not None:
            start_char = origin.evidence.location.start_char
            end_char = origin.evidence.location.end_char
    return FindingResponse(
        finding_id=finding.finding_id,
        component=None if current is None else current.component.value,
        display_text=None if current is None else current.display_text,
        page_number=finding_page_number(finding),
        evidence_status=None if current is None else current.evidence_status.value,
        removed=finding.removed,
        origin_kind=origin.kind,
        block_node_id=block_node_id,
        start_char=start_char,
        end_char=end_char,
        original_matched_text=original,
        added_by_user=finding.added_by_user is not None,
        changed_by_user=finding.changed_by_user is not None,
        removed_by_user=finding.removed_by_user is not None,
    )


def _json(model: ExtractionResponse) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


async def extraction_error_handler(request: Request, error: Exception) -> JSONResponse:
    if isinstance(error, ExtractionWorkspaceError):
        return JSONResponse(
            {"code": error.code, "message": error.message},
            status_code=error.status,
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        {"code": "EXTRACTION_REVIEW_FAILED", "message": "extraction review request failed"},
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


async def validation_error_handler(request: Request, error: Exception) -> Response:
    if "/api/v1/extraction-reviews" not in request.url.path:
        return await request_validation_exception_handler(
            request, cast(RequestValidationError, error)
        )
    return JSONResponse(
        {"code": "INVALID_REVIEW", "message": "extraction review request is invalid"},
        status_code=422,
        headers={"Cache-Control": "no-store"},
    )


def install_errors(app: FastAPI) -> None:
    app.add_exception_handler(ExtractionWorkspaceError, extraction_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

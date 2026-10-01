"""Local Stage 4 coordination for the extraction-review workspace.

Narrow adapter over approved-document selection, page classification, and the
classified Extract All lexical path. No generic workflow, queue, or classifier
management surface.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.extraction_review.approved_documents import (
    ApprovedDocumentError,
    ApprovedDocumentsRegistry,
    SelectedApprovedDocument,
)
from app.extraction_review.local_jobs import (
    CLASSIFICATION_SNAPSHOT_FILENAME,
    JOBS_DIR_NAME,
    ClassifiedFullExtractionError,
    ClassifiedFullJobSubmitted,
    LocalJobStatus,
    LocalLexicalJob,
    LocalLexicalJobNotFoundError,
    LocalLexicalJobService,
    LocalLexicalJobServiceAlreadyActiveError,
    LocalLexicalJobServiceBusyError,
    NoEligiblePagesForExtraction,
)
from app.extraction_review.page_html import render_reviewed_page_html
from app.extraction_review.workspace import ExtractionWorkspaceError, is_local_job_reviewable
from app.lexical_extraction.contracts import ReviewedHtmlV1Input
from app.lexical_extraction.html_reader import ReviewedHtmlReadError, open_reviewed_html
from app.page_classification.contracts import (
    CompletedPageClassificationResult,
    CurrentClassificationState,
    MergedLabelFinding,
)
from app.page_classification.service import PageClassificationBusyError, PageClassificationService
from app.page_classification.store import (
    PageClassificationStoreError,
    classification_snapshot_sha256,
)

logger = logging.getLogger("app.extraction_review.stage4_local")

_TERMINAL_CLASSIFICATION = frozenset({"completed", "failed", "interrupted"})
_TERMINAL_LEXICAL = frozenset(
    {
        LocalJobStatus.COMPLETED,
        LocalJobStatus.FAILED,
        LocalJobStatus.INTERRUPTED,
    }
)


class ClassificationServicePort(Protocol):
    """Minimal classification seam used by the local Stage 4 adapter."""

    def get_current(
        self,
        reviewed_html: ReviewedHtmlV1Input,
    ) -> CurrentClassificationState | None: ...

    def start_classification(
        self,
        reviewed_html_path: Path,
        *,
        expected: ReviewedHtmlV1Input,
    ) -> CurrentClassificationState: ...


class Stage4Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApprovedDocumentSummary(Stage4Model):
    job_id: str = Field(min_length=1)
    review_revision_id: str = Field(min_length=1)


class ClassificationEvidenceView(Stage4Model):
    label: str
    quote: str | None = None
    reason: str | None = None
    element_id: str | None = None
    evidence_verification: str | None = None
    evidence_verification_reason: str | None = None
    provenance: str | None = None


class SourceValidationView(Stage4Model):
    has_unverified: bool
    requires_review: bool
    items: tuple[ClassificationEvidenceView, ...]


class EligibilityView(Stage4Model):
    eligible_for_extraction: bool
    reason: str
    excluded_by_policy: bool


class PageClassificationView(Stage4Model):
    page_number: int = Field(ge=1)
    kind: str
    requires_review: bool
    is_provisional: bool
    applied_other_unclassified: bool
    labels: tuple[ClassificationEvidenceView, ...]
    evidence: tuple[ClassificationEvidenceView, ...]
    source_validation: SourceValidationView
    eligibility: EligibilityView


class ClassificationProgressView(Stage4Model):
    total_pages: int = Field(ge=0)
    completed_pages: int = Field(ge=0)
    current_page_number: int | None = None


class ClassificationStateView(Stage4Model):
    """Truthful classifier view for one approved reviewed-HTML binding."""

    job_id: str
    review_revision_id: str
    status: str
    progress: ClassificationProgressView
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    terminal_reason: str | None = None
    pages: tuple[PageClassificationView, ...]
    source: Literal["current", "job_snapshot"]


class ApprovedDocumentPagesView(Stage4Model):
    job_id: str
    review_revision_id: str
    pages: tuple[int, ...]


class LexicalJobStatusView(Stage4Model):
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


class ExtractAllSubmittedView(Stage4Model):
    kind: Literal["submitted"] = "submitted"
    job: LexicalJobStatusView


class ExtractAllNoEligibleView(Stage4Model):
    kind: Literal["no_eligible_pages"] = "no_eligible_pages"
    message: str


ExtractAllResultView = ExtractAllSubmittedView | ExtractAllNoEligibleView


class LocalStage4Adapter:
    """Coordinate approved-document Stage 4 actions for the local harness API."""

    def __init__(
        self,
        data_dir: Path,
        approved_documents_root: Path,
        *,
        classification_service: ClassificationServicePort | None = None,
        lexical_job_service: LocalLexicalJobService | None = None,
        config_path: Path | None = None,
        page_numbers_for: Callable[[SelectedApprovedDocument], tuple[int, ...]] | None = None,
    ) -> None:
        self._data_dir = data_dir.expanduser().resolve()
        self._approved_root = approved_documents_root.expanduser().resolve()
        self._registry = ApprovedDocumentsRegistry(self._approved_root)
        self._classification = classification_service
        self._lexical = lexical_job_service
        self._config_path = (
            None if config_path is None else Path(config_path).expanduser().resolve()
        )
        self._page_numbers_for = page_numbers_for or _page_numbers_for_selected
        self._page_cache: dict[tuple[str, str], tuple[int, ...]] = {}

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def approved_documents_root(self) -> Path:
        return self._approved_root

    @property
    def config_path(self) -> Path | None:
        return self._config_path

    def list_approved_documents(self) -> tuple[ApprovedDocumentSummary, ...]:
        try:
            page = self._registry.list_candidates(offset=0, page_size=100)
        except ApprovedDocumentError as exc:
            raise ExtractionWorkspaceError(
                "APPROVED_DOCUMENTS_UNAVAILABLE",
                _safe_approved_message(exc),
                404,
            ) from exc
        return tuple(
            ApprovedDocumentSummary(
                job_id=item.job_id,
                review_revision_id=item.review_revision_id,
            )
            for item in page.items
        )

    def document_pages(self, job_id: str, review_revision_id: str) -> ApprovedDocumentPagesView:
        selected = self._select(job_id, review_revision_id)
        pages = self._pages_for(selected)
        return ApprovedDocumentPagesView(
            job_id=job_id,
            review_revision_id=review_revision_id,
            pages=pages,
        )

    def approved_page_html(self, job_id: str, review_revision_id: str, page_number: int) -> str:
        selected = self._select(job_id, review_revision_id)
        pages = self._pages_for(selected)
        if page_number not in pages:
            raise ExtractionWorkspaceError("PAGE_NOT_FOUND", "reviewed page was not found", 404)
        try:
            document_html = selected.html_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ExtractionWorkspaceError(
                "DOCUMENT_NOT_AVAILABLE",
                "reviewed HTML for this document is not available",
                404,
            ) from exc
        rendered = render_reviewed_page_html(document_html, page_number, ())
        if rendered is None:
            raise ExtractionWorkspaceError("PAGE_NOT_FOUND", "reviewed page was not found", 404)
        return rendered

    def get_current_classification(
        self,
        job_id: str,
        review_revision_id: str,
    ) -> ClassificationStateView | None:
        selected = self._select(job_id, review_revision_id)
        service = self._require_classification_service()
        try:
            state = service.get_current(selected.reviewed_html)
        except PageClassificationStoreError as exc:
            raise ExtractionWorkspaceError(
                "CLASSIFICATION_UNAVAILABLE",
                "current classification could not be read",
                409,
            ) from exc
        if state is None:
            return None
        if state.reviewed_html != selected.reviewed_html:
            raise ExtractionWorkspaceError(
                "CLASSIFICATION_BINDING_MISMATCH",
                "classification binding does not match the selected reviewed HTML",
                409,
            )
        return classification_state_view(
            state,
            job_id=job_id,
            review_revision_id=review_revision_id,
            source="current",
        )

    def start_classification(
        self,
        job_id: str,
        review_revision_id: str,
    ) -> ClassificationStateView:
        selected = self._select(job_id, review_revision_id)
        service = self._require_classification_service()
        try:
            state = service.start_classification(
                selected.html_path,
                expected=selected.reviewed_html,
            )
        except PageClassificationBusyError as exc:
            raise ExtractionWorkspaceError(
                "CLASSIFICATION_BUSY",
                "page classification is already running for this local data directory",
                409,
            ) from exc
        except ApprovedDocumentError as exc:
            raise ExtractionWorkspaceError(
                "DOCUMENT_NOT_AVAILABLE",
                _safe_approved_message(exc),
                404,
            ) from exc
        except Exception as exc:
            logger.exception(
                "stage4_start_classification_failed job_id=%s review_revision_id=%s",
                job_id,
                review_revision_id,
            )
            raise ExtractionWorkspaceError(
                "CLASSIFICATION_START_FAILED",
                "page classification could not be started",
                503,
            ) from exc
        return classification_state_view(
            state,
            job_id=job_id,
            review_revision_id=review_revision_id,
            source="current",
        )

    def extract_all(self, job_id: str, review_revision_id: str) -> ExtractAllResultView:
        service = self._require_lexical_service()
        config_path = self._require_config_path()
        try:
            result = service.submit_classified_full_extraction(
                approved_documents_root=self._approved_root,
                job_id=job_id,
                review_revision_id=review_revision_id,
                config_path=config_path,
            )
        except ClassifiedFullExtractionError as exc:
            raise ExtractionWorkspaceError(
                exc.code,
                exc.message,
                _classified_status(exc.code),
            ) from exc
        except ApprovedDocumentError as exc:
            raise ExtractionWorkspaceError(
                "DOCUMENT_NOT_AVAILABLE",
                _safe_approved_message(exc),
                404,
            ) from exc
        except (LocalLexicalJobServiceAlreadyActiveError, LocalLexicalJobServiceBusyError) as exc:
            raise ExtractionWorkspaceError(
                "LEXICAL_SERVICE_BUSY",
                "local lexical extraction is busy or unavailable",
                409,
            ) from exc
        except Exception as exc:
            logger.exception(
                "stage4_extract_all_failed job_id=%s review_revision_id=%s",
                job_id,
                review_revision_id,
            )
            raise ExtractionWorkspaceError(
                "EXTRACT_ALL_FAILED",
                "classified Extract All could not be submitted",
                503,
            ) from exc
        if isinstance(result, NoEligiblePagesForExtraction):
            return ExtractAllNoEligibleView(message=result.message)
        assert isinstance(result, ClassifiedFullJobSubmitted)
        return ExtractAllSubmittedView(job=lexical_job_status_view(result.job))

    def lexical_job_status(self, local_job_id: str) -> LexicalJobStatusView:
        service = self._require_lexical_service()
        try:
            job = service.get_job(local_job_id)
        except LocalLexicalJobNotFoundError as exc:
            raise ExtractionWorkspaceError(
                "JOB_NOT_FOUND",
                "extraction job was not found",
                404,
            ) from exc
        return lexical_job_status_view(job)

    def classification_for_local_job(self, local_job_id: str) -> ClassificationStateView | None:
        """Return the immutable per-run classification snapshot for a classified job."""

        job = self._load_job_record(local_job_id)
        if job.classified_extraction is None:
            return None
        path = self._data_dir / JOBS_DIR_NAME / local_job_id / CLASSIFICATION_SNAPSHOT_FILENAME
        if not path.is_file():
            raise ExtractionWorkspaceError(
                "CLASSIFICATION_SNAPSHOT_MISSING",
                "classification snapshot for this extraction job is missing",
                409,
            )
        try:
            state = CurrentClassificationState.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise ExtractionWorkspaceError(
                "CLASSIFICATION_SNAPSHOT_INVALID",
                "classification snapshot for this extraction job is invalid",
                409,
            ) from exc
        digest = classification_snapshot_sha256(state)
        if digest != job.classified_extraction.snapshot_sha256:
            raise ExtractionWorkspaceError(
                "CLASSIFICATION_SNAPSHOT_DIGEST_MISMATCH",
                "classification snapshot digest does not match the extraction job",
                409,
            )
        selected = self._select(job.job_id, job.review_revision_id)
        if state.reviewed_html != selected.reviewed_html:
            raise ExtractionWorkspaceError(
                "CLASSIFICATION_BINDING_MISMATCH",
                "classification snapshot binding does not match the extraction job",
                409,
            )
        if job.reviewed_html is not None and state.reviewed_html != job.reviewed_html:
            raise ExtractionWorkspaceError(
                "CLASSIFICATION_BINDING_MISMATCH",
                "classification snapshot binding does not match the extraction job",
                409,
            )
        return classification_state_view(
            state,
            job_id=job.job_id,
            review_revision_id=job.review_revision_id,
            source="job_snapshot",
        )

    def _load_job_record(self, local_job_id: str) -> LocalLexicalJob:
        if self._lexical is not None:
            try:
                return self._lexical.get_job(local_job_id)
            except LocalLexicalJobNotFoundError as exc:
                raise ExtractionWorkspaceError(
                    "JOB_NOT_FOUND",
                    "extraction job was not found",
                    404,
                ) from exc
        path = self._data_dir / JOBS_DIR_NAME / f"{local_job_id}.json"
        if not path.is_file():
            raise ExtractionWorkspaceError(
                "JOB_NOT_FOUND",
                "extraction job was not found",
                404,
            )
        try:
            return LocalLexicalJob.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise ExtractionWorkspaceError(
                "JOB_NOT_FOUND",
                "extraction job was not found",
                404,
            ) from exc

    def _select(self, job_id: str, review_revision_id: str) -> SelectedApprovedDocument:
        try:
            return self._registry.select(job_id, review_revision_id)
        except ApprovedDocumentError as exc:
            raise ExtractionWorkspaceError(
                "DOCUMENT_NOT_AVAILABLE",
                _safe_approved_message(exc),
                404,
            ) from exc

    def _pages_for(self, selected: SelectedApprovedDocument) -> tuple[int, ...]:
        key = (selected.identity.job_id, selected.identity.review_revision_id)
        cached = self._page_cache.get(key)
        if cached is not None:
            return cached
        try:
            pages = self._page_numbers_for(selected)
        except ReviewedHtmlReadError as exc:
            raise ExtractionWorkspaceError(
                "DOCUMENT_NOT_AVAILABLE",
                "reviewed HTML for this document is not available",
                404,
            ) from exc
        self._page_cache[key] = pages
        return pages

    def _require_classification_service(self) -> ClassificationServicePort:
        if self._classification is None:
            raise ExtractionWorkspaceError(
                "CLASSIFIER_UNAVAILABLE",
                "page classification is not configured for this local workspace",
                503,
            )
        return self._classification

    def _require_lexical_service(self) -> LocalLexicalJobService:
        if self._lexical is None:
            raise ExtractionWorkspaceError(
                "EXTRACT_ALL_UNAVAILABLE",
                "classified Extract All is not configured for this local workspace",
                503,
            )
        return self._lexical

    def _require_config_path(self) -> Path:
        if self._config_path is None or not self._config_path.is_file():
            raise ExtractionWorkspaceError(
                "EXTRACT_ALL_UNAVAILABLE",
                "classified Extract All is not configured for this local workspace",
                503,
            )
        return self._config_path


def classification_state_view(
    state: CurrentClassificationState,
    *,
    job_id: str,
    review_revision_id: str,
    source: Literal["current", "job_snapshot"],
) -> ClassificationStateView:
    return ClassificationStateView(
        job_id=job_id,
        review_revision_id=review_revision_id,
        status=state.status,
        progress=ClassificationProgressView(
            total_pages=state.progress.total_pages,
            completed_pages=state.progress.completed_pages,
            current_page_number=state.progress.current_page_number,
        ),
        created_at=state.created_at,
        updated_at=state.updated_at,
        finished_at=state.finished_at,
        terminal_reason=state.terminal_reason,
        pages=tuple(_page_view(page) for page in state.page_results),
        source=source,
    )


def lexical_job_status_view(job: LocalLexicalJob) -> LexicalJobStatusView:
    error_code = None if job.error is None else job.error.code
    error_message = None if job.error is None else job.error.message
    selected = None
    if job.classified_extraction is not None:
        selected = job.classified_extraction.selected_page_numbers
    extraction_overall = None if job.extraction is None else job.extraction.overall.value
    return LexicalJobStatusView(
        local_job_id=job.local_job_id,
        job_id=job.job_id,
        review_revision_id=job.review_revision_id,
        status=job.status.value,
        phase=job.phase.value,
        action=job.action.value,
        submitted_at=job.submitted_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_code=error_code,
        error_message=error_message,
        classified=job.classified_extraction is not None,
        selected_page_numbers=selected,
        extraction_overall=extraction_overall,
        reviewable=is_local_job_reviewable(job),
    )


def is_terminal_classification_status(status: str) -> bool:
    return status in _TERMINAL_CLASSIFICATION


def is_terminal_lexical_status(status: LocalJobStatus | str) -> bool:
    if isinstance(status, LocalJobStatus):
        return status in _TERMINAL_LEXICAL
    try:
        return LocalJobStatus(status) in _TERMINAL_LEXICAL
    except ValueError:
        return False


def build_local_stage4_adapter(
    *,
    data_dir: Path,
    approved_documents_root: Path,
    config_path: Path | None = None,
    classification_service: ClassificationServicePort | None = None,
    lexical_job_service: LocalLexicalJobService | None = None,
    settings_factory: Callable[[], object] | None = None,
    openai_client_factory: Callable[..., object] | None = None,
    wrapper_factory: Callable[..., object] | None = None,
) -> LocalStage4Adapter:
    """Compose the local Stage 4 adapter from existing settings and OpenAI seams.

    Does not modify settings or the OpenAI wrapper. Real HTTP requests are never
    made here; the wrapper is only constructed for later classifier use.
    """

    resolved_classification = classification_service
    if resolved_classification is None:
        resolved_classification = _compose_classification_service(
            data_dir,
            settings_factory=settings_factory,
            openai_client_factory=openai_client_factory,
            wrapper_factory=wrapper_factory,
        )

    resolved_lexical = lexical_job_service
    resolved_config = None if config_path is None else Path(config_path).expanduser().resolve()
    if resolved_lexical is None and resolved_config is not None and resolved_config.is_file():
        try:
            resolved_lexical = LocalLexicalJobService(data_dir)
        except LocalLexicalJobServiceAlreadyActiveError:
            logger.warning("stage4_lexical_service_already_active data_dir=%s", data_dir)
            resolved_lexical = None

    return LocalStage4Adapter(
        data_dir,
        approved_documents_root,
        classification_service=resolved_classification,
        lexical_job_service=resolved_lexical,
        config_path=resolved_config,
    )


def _compose_classification_service(
    data_dir: Path,
    *,
    settings_factory: Callable[[], object] | None,
    openai_client_factory: Callable[..., object] | None,
    wrapper_factory: Callable[..., object] | None,
) -> PageClassificationService | None:
    try:
        from app.llm import AsyncOpenAIWrapper, create_async_openai_client
        from app.settings import get_settings
    except Exception:  # noqa: BLE001 - composition must stay startable without LLM
        logger.warning("stage4_classifier_composition_imports_unavailable")
        return None

    load_settings = settings_factory or get_settings
    build_client = openai_client_factory or create_async_openai_client
    build_wrapper = wrapper_factory or AsyncOpenAIWrapper

    try:
        settings = load_settings()
        api_key = getattr(settings, "openai_api_key", None)
        if not api_key:
            return None
        client = build_client(
            api_key=api_key,
            timeout_seconds=float(getattr(settings, "openai_timeout_seconds", 20.0)),
        )
        wrapper = build_wrapper(
            client=client,  # type: ignore[arg-type]
            default_model=str(getattr(settings, "openai_model", "gpt-4.1-mini")),
            timeout_seconds=float(getattr(settings, "openai_timeout_seconds", 20.0)),
            max_retries=int(getattr(settings, "openai_max_retries", 2)),
        )
        return PageClassificationService(data_dir, wrapper)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - keep harness startable when OpenAI is unset/invalid
        logger.exception("stage4_classifier_composition_failed")
        return None


def _page_view(page: CompletedPageClassificationResult) -> PageClassificationView:
    labels = tuple(_label_view(item) for item in page.labels)
    evidence = tuple(_label_view(item) for item in page.labels if _has_evidence(item))
    validation_items = tuple(
        ClassificationEvidenceView(
            label=item.label,
            quote=item.quote,
            reason=item.reason,
            element_id=item.element_id,
            evidence_verification=item.verification,
            evidence_verification_reason=item.verification_reason,
        )
        for item in page.source_validation.items
    )
    return PageClassificationView(
        page_number=page.binding.page_number,
        kind=page.kind,
        requires_review=page.requires_review,
        is_provisional=page.is_provisional,
        applied_other_unclassified=page.applied_other_unclassified,
        labels=labels,
        evidence=evidence,
        source_validation=SourceValidationView(
            has_unverified=page.source_validation.has_unverified,
            requires_review=page.source_validation.requires_review,
            items=validation_items,
        ),
        eligibility=EligibilityView(
            eligible_for_extraction=page.eligibility.eligible_for_extraction,
            reason=page.eligibility.reason,
            excluded_by_policy=page.eligibility.excluded_by_policy,
        ),
    )


def _label_view(item: MergedLabelFinding) -> ClassificationEvidenceView:
    return ClassificationEvidenceView(
        label=item.label,
        quote=item.quote,
        reason=item.reason,
        element_id=item.element_id,
        evidence_verification=item.evidence_verification,
        evidence_verification_reason=item.evidence_verification_reason,
        provenance=item.provenance,
    )


def _has_evidence(item: MergedLabelFinding) -> bool:
    return bool(item.quote or item.reason or item.element_id)


def _page_numbers_for_selected(selected: SelectedApprovedDocument) -> tuple[int, ...]:
    reader = open_reviewed_html(selected.html_path)
    numbers: list[int] = []
    try:
        for page in reader.iter_pages():
            numbers.append(page.page.page_number)
    except ReviewedHtmlReadError:
        raise
    if not reader.completed:
        raise ReviewedHtmlReadError("DOCUMENT_INCOMPLETE", "reviewed HTML was incomplete")
    return tuple(numbers)


def _safe_approved_message(exc: ApprovedDocumentError) -> str:
    text = " ".join(exc.message.split())
    if "/" in text or "\\" in text or len(text) > 200:
        return "reviewed HTML for this document is not available"
    return text or "reviewed HTML for this document is not available"


def _classified_status(code: str) -> int:
    if code in {"CLASSIFICATION_MISSING", "DOCUMENT_NOT_AVAILABLE"}:
        return 404
    if code in {
        "CLASSIFICATION_RUNNING",
        "CLASSIFICATION_NOT_TERMINAL",
        "CLASSIFICATION_BINDING_MISMATCH",
    }:
        return 409
    return 422


__all__ = [
    "ApprovedDocumentPagesView",
    "ApprovedDocumentSummary",
    "ClassificationEvidenceView",
    "ClassificationProgressView",
    "ClassificationServicePort",
    "ClassificationStateView",
    "EligibilityView",
    "ExtractAllNoEligibleView",
    "ExtractAllResultView",
    "ExtractAllSubmittedView",
    "LexicalJobStatusView",
    "LocalStage4Adapter",
    "PageClassificationView",
    "SourceValidationView",
    "build_local_stage4_adapter",
    "classification_state_view",
    "is_terminal_classification_status",
    "is_terminal_lexical_status",
    "lexical_job_status_view",
]

"""Application-owned page-classification contracts.

These models describe prepared document/page inputs, call outcomes,
source-evidence validation, merged page results, extraction eligibility,
and the current-classification persistence envelope used by local execution.
They do not call an LLM or route Stage 2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.lexical_extraction.contracts import ReviewedHtmlV1Input
from app.page_classification.page_classification_schemas import (
    DocumentSupportingResponse,
    MaterialEquipmentResponse,
    ProcessOperationsResponse,
    ResponseStatus,
)

ClassifierCallId: TypeAlias = Literal[1, 2, 3]
CallAvailability: TypeAlias = Literal["valid", "missing", "failed", "invalid"]
MergedPageKind: TypeAlias = Literal[
    "completed",
    "empty",
    "incomplete",
    "needs_review",
]
EvidenceVerificationStatus: TypeAlias = Literal["verified", "unverified"]
LabelProvenance: TypeAlias = Literal["call", "application_fallback"]

ClassifierResponse: TypeAlias = (
    MaterialEquipmentResponse | ProcessOperationsResponse | DocumentSupportingResponse
)

_CALL_RESPONSE_MODELS: dict[ClassifierCallId, type[ClassifierResponse]] = {
    1: MaterialEquipmentResponse,
    2: ProcessOperationsResponse,
    3: DocumentSupportingResponse,
}

OTHER_UNCLASSIFIED: Literal["OTHER_UNCLASSIFIED"] = "OTHER_UNCLASSIFIED"

EXCLUSION_LABELS: frozenset[str] = frozenset(
    {
        "NON_RELATED",
        "COVER_PAGE",
        "TABLE_OF_CONTENTS",
        "DOCUMENTATION_INSTRUCTIONS",
        "REFERENCE_DOCUMENTATION",
        "SIGNATURE_LOG",
        "SIGNATURE_APPROVAL",
        "ACKNOWLEDGEMENT",
        "BATCH_REVIEW_DISPOSITION",
        "DOCUMENT_CHANGE_HISTORY",
    }
)


class PageClassificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PageInputBinding(PageClassificationModel):
    """Identity binding shared by a prepared page and its call outcomes."""

    reviewed_html: ReviewedHtmlV1Input
    page_number: int = Field(strict=True, ge=1)
    page_html_id: str = Field(min_length=1)


class PreparedPageInput(PageClassificationModel):
    """One prepared page derived from a fully validated reviewed-HTML document."""

    binding: PageInputBinding
    page_html_fragment: str = Field(min_length=1)
    readable_text: str
    element_text_by_id: dict[str, str]
    ambiguous_element_ids: frozenset[str]


class PreparedDocument(PageClassificationModel):
    """Document prepared once; page lookup must not revalidate the whole document."""

    reviewed_html: ReviewedHtmlV1Input
    pages: tuple[PreparedPageInput, ...]


class CallOutcome(PageClassificationModel):
    """One of the three fixed classifier call slots for a prepared page."""

    binding: PageInputBinding
    call_id: ClassifierCallId
    availability: CallAvailability
    response: ClassifierResponse | None = None
    failure_reason: str | None = None


class EvidenceValidationItem(PageClassificationModel):
    """Source check for one structurally valid evidence item."""

    call_id: ClassifierCallId
    label: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    element_id: str | None
    verification: EvidenceVerificationStatus
    verification_reason: str | None = None


class SourceEvidenceValidation(PageClassificationModel):
    """Source-evidence results for one page's valid call outcomes."""

    binding: PageInputBinding
    items: tuple[EvidenceValidationItem, ...]
    has_unverified: bool
    requires_review: bool


class MergedLabelFinding(PageClassificationModel):
    """One merged label with preserved evidence and originating call."""

    label: str = Field(min_length=1)
    call_id: ClassifierCallId | None = None
    quote: str | None = None
    reason: str | None = None
    element_id: str | None = None
    provenance: LabelProvenance
    evidence_verification: EvidenceVerificationStatus | None = None
    evidence_verification_reason: str | None = None


class MergedPageClassification(PageClassificationModel):
    """Deterministic merge of the three call outcomes for one page binding."""

    binding: PageInputBinding
    kind: MergedPageKind
    labels: tuple[MergedLabelFinding, ...]
    call_outcomes: tuple[CallOutcome, ...]
    source_validation: SourceEvidenceValidation
    response_statuses: tuple[ResponseStatus | None, ResponseStatus | None, ResponseStatus | None]
    reasons: tuple[str, ...]
    requires_review: bool
    is_provisional: bool
    applied_other_unclassified: bool


class EligibilityDecision(PageClassificationModel):
    """Conservative extraction eligibility from a merged page classification."""

    binding: PageInputBinding
    eligible_for_extraction: bool
    reason: str = Field(min_length=1)
    excluded_by_policy: bool


ClassificationLifecycleStatus: TypeAlias = Literal[
    "running",
    "completed",
    "failed",
    "interrupted",
]

CURRENT_CLASSIFICATION_SCHEMA_VERSION: Literal["batchlens.page-classification-current.v1"] = (
    "batchlens.page-classification-current.v1"
)
CLASSIFIER_POLICY_CONTRACT_VERSION: Literal["batchlens.page-classification-policy.v1"] = (
    "batchlens.page-classification-policy.v1"
)


class PersistedCallOutcome(PageClassificationModel):
    """Call-id-keyed persistence for one classifier call slot.

    Response payloads are stored as plain JSON objects and reconstructed with
    the fixed ``call_id`` so empty responses cannot be mis-attributed across
    the three schema-identical LLM response models.
    """

    binding: PageInputBinding
    call_id: ClassifierCallId
    availability: CallAvailability
    response: dict[str, Any] | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def _check_response_presence(self) -> PersistedCallOutcome:
        if self.availability == "valid":
            if self.response is None:
                raise ValueError("valid call outcomes require a response payload")
            if self.failure_reason is not None:
                raise ValueError("valid call outcomes must not include a failure reason")
            schema = _CALL_RESPONSE_MODELS[self.call_id]
            try:
                schema.model_validate(self.response)
            except ValidationError as exc:
                raise ValueError(
                    f"valid call {self.call_id} response failed schema validation "
                    f"for {schema.__name__}"
                ) from exc
        elif self.response is not None:
            raise ValueError("non-valid call outcomes must not include a response payload")
        return self


class ClassificationProgress(PageClassificationModel):
    """Truthful page-classification progress for the current reviewed document."""

    total_pages: int = Field(strict=True, ge=0)
    completed_pages: int = Field(strict=True, ge=0)
    current_page_number: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode="after")
    def _check_counts(self) -> ClassificationProgress:
        if self.completed_pages > self.total_pages:
            raise ValueError("completed_pages cannot exceed total_pages")
        return self


class CompletedPageClassificationResult(PageClassificationModel):
    """One finished page: three call outcomes, merge, and eligibility."""

    binding: PageInputBinding
    call_outcomes: tuple[
        PersistedCallOutcome,
        PersistedCallOutcome,
        PersistedCallOutcome,
    ]
    source_validation: SourceEvidenceValidation
    kind: MergedPageKind
    labels: tuple[MergedLabelFinding, ...]
    response_statuses: tuple[
        ResponseStatus | None,
        ResponseStatus | None,
        ResponseStatus | None,
    ]
    reasons: tuple[str, ...]
    requires_review: bool
    is_provisional: bool
    applied_other_unclassified: bool
    eligibility: EligibilityDecision

    @field_validator("call_outcomes")
    @classmethod
    def _ordered_call_ids(
        cls,
        value: tuple[PersistedCallOutcome, PersistedCallOutcome, PersistedCallOutcome],
    ) -> tuple[PersistedCallOutcome, PersistedCallOutcome, PersistedCallOutcome]:
        call_ids = [item.call_id for item in value]
        if call_ids != [1, 2, 3]:
            raise ValueError("call_outcomes must be exactly calls 1, 2, and 3 in order")
        return value

    @model_validator(mode="after")
    def _binding_consistency(self) -> CompletedPageClassificationResult:
        binding = self.binding
        if self.source_validation.binding != binding:
            raise ValueError("source_validation binding must match page binding")
        if self.eligibility.binding != binding:
            raise ValueError("eligibility binding must match page binding")
        for outcome in self.call_outcomes:
            if outcome.binding != binding:
                raise ValueError("call outcome binding must match page binding")
        return self


class CurrentClassificationState(PageClassificationModel):
    """One current classification state for a reviewed-HTML identity."""

    schema_version: Literal["batchlens.page-classification-current.v1"] = (
        CURRENT_CLASSIFICATION_SCHEMA_VERSION
    )
    classifier_policy_version: Literal["batchlens.page-classification-policy.v1"] = (
        CLASSIFIER_POLICY_CONTRACT_VERSION
    )
    reviewed_html: ReviewedHtmlV1Input
    status: ClassificationLifecycleStatus
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    progress: ClassificationProgress
    page_results: tuple[CompletedPageClassificationResult, ...] = ()
    terminal_reason: str | None = None
    classification_run_id: str | None = None

    @model_validator(mode="after")
    def _lifecycle_invariants(self) -> CurrentClassificationState:
        progress = self.progress
        results = self.page_results
        if len(results) != progress.completed_pages:
            raise ValueError("page_results length must equal completed_pages")
        page_numbers = [item.binding.page_number for item in results]
        if page_numbers != sorted(page_numbers):
            raise ValueError("page_results must be in document/page order")
        if len(set(page_numbers)) != len(page_numbers):
            raise ValueError("page_results must not contain duplicate page numbers")
        for item in results:
            if item.binding.reviewed_html != self.reviewed_html:
                raise ValueError("page result binding must match reviewed_html identity")

        if self.status == "completed":
            if progress.completed_pages != progress.total_pages:
                raise ValueError("completed state requires every page result")
            if progress.current_page_number is not None:
                raise ValueError("completed state must not retain a current page")
            if self.finished_at is None:
                raise ValueError("completed state requires finished_at")
            if self.terminal_reason is not None:
                raise ValueError("completed state must not include a terminal reason")
            return self

        if self.status == "running":
            if progress.completed_pages >= progress.total_pages and progress.total_pages > 0:
                raise ValueError("running state cannot claim all pages completed")
            if self.finished_at is not None:
                raise ValueError("running state must not include finished_at")
            if self.terminal_reason is not None:
                raise ValueError("running state must not include a terminal reason")
            return self

        # failed or interrupted
        if progress.completed_pages == progress.total_pages and progress.total_pages > 0:
            raise ValueError(
                f"{self.status} state cannot claim all pages completed unless terminal"
            )
        if self.finished_at is None:
            raise ValueError(f"{self.status} state requires finished_at")
        if self.terminal_reason is None or not self.terminal_reason.strip():
            raise ValueError(f"{self.status} state requires a terminal reason")
        if progress.current_page_number is not None:
            raise ValueError(f"{self.status} state must not retain a current page")
        return self


def persist_call_outcome(outcome: CallOutcome) -> PersistedCallOutcome:
    """Serialize one runtime call outcome for current-state persistence."""

    response_payload: dict[str, Any] | None = None
    if outcome.response is not None:
        response_payload = outcome.response.model_dump(mode="json")
    return PersistedCallOutcome(
        binding=outcome.binding,
        call_id=outcome.call_id,
        availability=outcome.availability,
        response=response_payload,
        failure_reason=outcome.failure_reason,
    )


def completed_page_result_from_merge(
    merged: MergedPageClassification,
    eligibility: EligibilityDecision,
) -> CompletedPageClassificationResult:
    """Build a persistable page result from S4.1 merge and eligibility outputs."""

    if eligibility.binding != merged.binding:
        raise ValueError("eligibility binding must match merged page binding")
    ordered = tuple(persist_call_outcome(item) for item in merged.call_outcomes)
    if len(ordered) != 3:
        raise ValueError("merged classification must include three call outcomes")
    return CompletedPageClassificationResult(
        binding=merged.binding,
        call_outcomes=(ordered[0], ordered[1], ordered[2]),
        source_validation=merged.source_validation,
        kind=merged.kind,
        labels=merged.labels,
        response_statuses=merged.response_statuses,
        reasons=merged.reasons,
        requires_review=merged.requires_review,
        is_provisional=merged.is_provisional,
        applied_other_unclassified=merged.applied_other_unclassified,
        eligibility=eligibility,
    )


__all__ = [
    "CallAvailability",
    "CallOutcome",
    "CLASSIFIER_POLICY_CONTRACT_VERSION",
    "ClassificationLifecycleStatus",
    "ClassificationProgress",
    "ClassifierCallId",
    "ClassifierResponse",
    "CompletedPageClassificationResult",
    "CURRENT_CLASSIFICATION_SCHEMA_VERSION",
    "CurrentClassificationState",
    "EligibilityDecision",
    "EvidenceValidationItem",
    "EvidenceVerificationStatus",
    "EXCLUSION_LABELS",
    "LabelProvenance",
    "MergedLabelFinding",
    "MergedPageClassification",
    "MergedPageKind",
    "OTHER_UNCLASSIFIED",
    "PageInputBinding",
    "PageClassificationModel",
    "PersistedCallOutcome",
    "PreparedDocument",
    "PreparedPageInput",
    "SourceEvidenceValidation",
    "completed_page_result_from_merge",
    "persist_call_outcome",
]

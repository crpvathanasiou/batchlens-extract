"""Pure structured validation, source checks, merge, and eligibility rules."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.page_classification.contracts import (
    EXCLUSION_LABELS,
    OTHER_UNCLASSIFIED,
    CallOutcome,
    ClassifierCallId,
    ClassifierResponse,
    EligibilityDecision,
    EvidenceValidationItem,
    MergedLabelFinding,
    MergedPageClassification,
    PageInputBinding,
    PreparedPageInput,
    SourceEvidenceValidation,
)
from app.page_classification.page_classification_schemas import (
    DocumentSupportingResponse,
    MaterialEquipmentResponse,
    ProcessOperationsResponse,
    ResponseStatus,
)
from app.page_classification.page_input import normalize_evidence_text

_CALL_MODELS: dict[ClassifierCallId, type[ClassifierResponse]] = {
    1: MaterialEquipmentResponse,
    2: ProcessOperationsResponse,
    3: DocumentSupportingResponse,
}

_FALLBACK_REASON = (
    "all three classifier calls returned ok with an empty label union; "
    "application assigned OTHER_UNCLASSIFIED"
)


def missing_call(binding: PageInputBinding, call_id: ClassifierCallId) -> CallOutcome:
    return CallOutcome(
        binding=binding,
        call_id=call_id,
        availability="missing",
        response=None,
        failure_reason="classifier call response was not supplied",
    )


def failed_call(
    binding: PageInputBinding,
    call_id: ClassifierCallId,
    *,
    reason: str,
) -> CallOutcome:
    return CallOutcome(
        binding=binding,
        call_id=call_id,
        availability="failed",
        response=None,
        failure_reason=reason,
    )


def validate_call_response(
    binding: PageInputBinding,
    call_id: ClassifierCallId,
    payload: Any,
) -> CallOutcome:
    """Validate one supplied response payload or constructed model instance."""

    model = _CALL_MODELS[call_id]
    try:
        if isinstance(payload, model):
            response = model.model_validate(payload)
        else:
            response = model.model_validate(payload)
    except ValidationError as exc:
        return CallOutcome(
            binding=binding,
            call_id=call_id,
            availability="invalid",
            response=None,
            failure_reason=_validation_reason(exc),
        )
    except Exception as exc:  # noqa: BLE001 - preserve explicit invalid outcome
        return CallOutcome(
            binding=binding,
            call_id=call_id,
            availability="invalid",
            response=None,
            failure_reason=f"response validation failed: {exc}",
        )
    return CallOutcome(
        binding=binding,
        call_id=call_id,
        availability="valid",
        response=response,
        failure_reason=None,
    )


def validate_source_evidence(
    page: PreparedPageInput,
    outcomes: tuple[CallOutcome, CallOutcome, CallOutcome],
) -> SourceEvidenceValidation:
    """Verify quotes/IDs for every structurally valid evidence item on one page.

    Requires exactly one outcome for call IDs 1, 2, and 3. Applies the same
    one-decode evidence normalization to page text, element text, and quotes.
    """

    ordered = _ordered_outcomes(outcomes)
    _require_same_binding(page.binding, ordered)
    items: list[EvidenceValidationItem] = []
    normalized_page = normalize_evidence_text(page.readable_text)
    for outcome in ordered:
        if outcome.availability != "valid" or outcome.response is None:
            continue
        for evidence in outcome.response.evidence:
            item = _validate_one_evidence(
                call_id=outcome.call_id,
                label=str(evidence.label),
                quote=evidence.quote,
                reason=evidence.reason,
                element_id=evidence.element_id,
                normalized_page=normalized_page,
                element_text_by_id=page.element_text_by_id,
            )
            items.append(item)
    has_unverified = any(item.verification == "unverified" for item in items)
    return SourceEvidenceValidation(
        binding=page.binding,
        items=tuple(items),
        has_unverified=has_unverified,
        requires_review=has_unverified,
    )


def merge_page_classification(
    page: PreparedPageInput,
    outcomes: tuple[CallOutcome, CallOutcome, CallOutcome],
) -> MergedPageClassification:
    """Merge the three fixed call outcomes for one prepared page binding.

    Always computes source-evidence validation from the prepared page and the
    ordered call outcomes. Callers cannot supply or bypass that validation.
    """

    _require_same_binding(page.binding, outcomes)
    ordered = _ordered_outcomes(outcomes)
    source_validation = validate_source_evidence(page, ordered)

    statuses: list[ResponseStatus | None] = []
    reasons: list[str] = []
    incomplete = False
    for outcome in ordered:
        if outcome.availability != "valid" or outcome.response is None:
            incomplete = True
            statuses.append(None)
            reasons.append(
                f"call {outcome.call_id} is {outcome.availability}"
                + (f": {outcome.failure_reason}" if outcome.failure_reason else "")
            )
            continue
        statuses.append(outcome.response.status)

    findings = _collect_findings(ordered, source_validation)
    response_statuses = (statuses[0], statuses[1], statuses[2])
    requires_review = source_validation.requires_review
    applied_fallback = False

    if incomplete:
        if source_validation.has_unverified:
            reasons.append("source evidence verification failed for one or more labels")
            requires_review = True
        return MergedPageClassification(
            binding=page.binding,
            kind="incomplete",
            labels=tuple(findings),
            call_outcomes=ordered,
            source_validation=source_validation,
            response_statuses=response_statuses,
            reasons=tuple(reasons),
            requires_review=requires_review,
            is_provisional=True,
            applied_other_unclassified=False,
        )

    assert all(status is not None for status in statuses)
    concrete_statuses = (statuses[0], statuses[1], statuses[2])
    assert concrete_statuses[0] is not None
    assert concrete_statuses[1] is not None
    assert concrete_statuses[2] is not None

    if any(status == "needs_review" for status in concrete_statuses):
        reasons.append("at least one valid response has status needs_review")
        requires_review = True
        kind: str = "needs_review"
    elif all(status == "empty" for status in concrete_statuses):
        reasons.append("all three valid responses have status empty")
        kind = "empty"
        findings = []
    elif "empty" in concrete_statuses and "ok" in concrete_statuses:
        reasons.append("valid responses disagree between empty and ok")
        requires_review = True
        kind = "needs_review"
    elif all(status == "ok" for status in concrete_statuses):
        if findings:
            kind = "completed"
            reasons.append("all three responses are ok with a nonempty label union")
        else:
            applied_fallback = True
            requires_review = True
            kind = "needs_review"
            findings = [
                MergedLabelFinding(
                    label=OTHER_UNCLASSIFIED,
                    call_id=None,
                    quote=None,
                    reason=_FALLBACK_REASON,
                    element_id=None,
                    provenance="application_fallback",
                    evidence_verification=None,
                    evidence_verification_reason=None,
                )
            ]
            reasons.append(_FALLBACK_REASON)
    else:
        # needs_review mixed with empty/ok without the empty/ok-only conflict above.
        reasons.append("valid responses require review")
        requires_review = True
        kind = "needs_review"

    if source_validation.has_unverified:
        reasons.append("source evidence verification failed for one or more labels")
        requires_review = True
        if kind == "completed":
            kind = "needs_review"

    return MergedPageClassification(
        binding=page.binding,
        kind=kind,  # type: ignore[arg-type]
        labels=tuple(findings),
        call_outcomes=ordered,
        source_validation=source_validation,
        response_statuses=response_statuses,
        reasons=tuple(reasons),
        requires_review=requires_review,
        is_provisional=False,
        applied_other_unclassified=applied_fallback,
    )


def decide_extraction_eligibility(
    merged: MergedPageClassification,
) -> EligibilityDecision:
    """Apply the fixed S4.1 exclusion policy to a merged page classification."""

    labels = tuple(item.label for item in merged.labels)
    if merged.kind == "incomplete" or merged.is_provisional:
        return EligibilityDecision(
            binding=merged.binding,
            eligible_for_extraction=True,
            reason="page classification is incomplete; page remains eligible",
            excluded_by_policy=False,
        )
    if any(outcome.availability != "valid" for outcome in merged.call_outcomes):
        return EligibilityDecision(
            binding=merged.binding,
            eligible_for_extraction=True,
            reason="not all classifier calls are structurally valid; page remains eligible",
            excluded_by_policy=False,
        )
    if merged.requires_review or merged.kind == "needs_review":
        return EligibilityDecision(
            binding=merged.binding,
            eligible_for_extraction=True,
            reason="page requires review; page remains eligible",
            excluded_by_policy=False,
        )
    if merged.source_validation.has_unverified:
        return EligibilityDecision(
            binding=merged.binding,
            eligible_for_extraction=True,
            reason="source evidence is unverified; page remains eligible",
            excluded_by_policy=False,
        )
    if merged.applied_other_unclassified or OTHER_UNCLASSIFIED in labels:
        return EligibilityDecision(
            binding=merged.binding,
            eligible_for_extraction=True,
            reason="application fallback OTHER_UNCLASSIFIED remains eligible",
            excluded_by_policy=False,
        )
    if merged.kind == "empty" or not labels:
        return EligibilityDecision(
            binding=merged.binding,
            eligible_for_extraction=True,
            reason="empty classification remains eligible",
            excluded_by_policy=False,
        )
    if all(label in EXCLUSION_LABELS for label in labels):
        return EligibilityDecision(
            binding=merged.binding,
            eligible_for_extraction=False,
            reason=("every final label belongs to the fixed exclusion set: " + ", ".join(labels)),
            excluded_by_policy=True,
        )
    return EligibilityDecision(
        binding=merged.binding,
        eligible_for_extraction=True,
        reason="final labels are not exclusively exclusion labels; page remains eligible",
        excluded_by_policy=False,
    )


def _validate_one_evidence(
    *,
    call_id: ClassifierCallId,
    label: str,
    quote: str,
    reason: str,
    element_id: str | None,
    normalized_page: str,
    element_text_by_id: dict[str, str],
) -> EvidenceValidationItem:
    normalized_quote = normalize_evidence_text(quote)
    if not normalized_quote:
        return EvidenceValidationItem(
            call_id=call_id,
            label=label,
            quote=quote,
            reason=reason,
            element_id=element_id,
            verification="unverified",
            verification_reason="normalized quote is empty",
        )
    if normalized_quote not in normalized_page:
        return EvidenceValidationItem(
            call_id=call_id,
            label=label,
            quote=quote,
            reason=reason,
            element_id=element_id,
            verification="unverified",
            verification_reason="quote not found in normalized page text",
        )
    if element_id is None:
        return EvidenceValidationItem(
            call_id=call_id,
            label=label,
            quote=quote,
            reason=reason,
            element_id=element_id,
            verification="verified",
            verification_reason=None,
        )
    element_text = element_text_by_id.get(element_id)
    if element_text is None:
        return EvidenceValidationItem(
            call_id=call_id,
            label=label,
            quote=quote,
            reason=reason,
            element_id=element_id,
            verification="unverified",
            verification_reason=f"element_id not found on prepared page: {element_id}",
        )
    if normalized_quote not in normalize_evidence_text(element_text):
        return EvidenceValidationItem(
            call_id=call_id,
            label=label,
            quote=quote,
            reason=reason,
            element_id=element_id,
            verification="unverified",
            verification_reason="quote not found in normalized element text",
        )
    return EvidenceValidationItem(
        call_id=call_id,
        label=label,
        quote=quote,
        reason=reason,
        element_id=element_id,
        verification="verified",
        verification_reason=None,
    )


def _collect_findings(
    outcomes: tuple[CallOutcome, CallOutcome, CallOutcome],
    source_validation: SourceEvidenceValidation,
) -> list[MergedLabelFinding]:
    by_key = {(item.call_id, item.label): item for item in source_validation.items}
    findings: list[MergedLabelFinding] = []
    for outcome in outcomes:
        if outcome.availability != "valid" or outcome.response is None:
            continue
        for evidence in outcome.response.evidence:
            key = (outcome.call_id, str(evidence.label))
            checked = by_key.get(key)
            findings.append(
                MergedLabelFinding(
                    label=str(evidence.label),
                    call_id=outcome.call_id,
                    quote=evidence.quote,
                    reason=evidence.reason,
                    element_id=evidence.element_id,
                    provenance="call",
                    evidence_verification=(None if checked is None else checked.verification),
                    evidence_verification_reason=(
                        None if checked is None else checked.verification_reason
                    ),
                )
            )
    return findings


def _ordered_outcomes(
    outcomes: tuple[CallOutcome, CallOutcome, CallOutcome],
) -> tuple[CallOutcome, CallOutcome, CallOutcome]:
    if len(outcomes) != 3:
        raise ValueError("exactly three call outcomes are required for calls 1, 2, and 3")
    call_ids = [outcome.call_id for outcome in outcomes]
    if sorted(call_ids) != [1, 2, 3]:
        raise ValueError(
            "source validation and merge require exactly one outcome for calls 1, 2, and 3"
        )
    ordered = tuple(sorted(outcomes, key=lambda item: item.call_id))
    return (ordered[0], ordered[1], ordered[2])


def _require_same_binding(
    binding: PageInputBinding,
    outcomes: tuple[CallOutcome, CallOutcome, CallOutcome],
) -> None:
    for outcome in outcomes:
        if outcome.binding != binding:
            raise ValueError("call outcome binding does not match the prepared page binding")


def _validation_reason(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "response failed schema validation"
    first = errors[0]
    error_type = str(first.get("type", "validation_error"))
    return f"response failed schema validation: {error_type}"


__all__ = [
    "decide_extraction_eligibility",
    "failed_call",
    "merge_page_classification",
    "missing_call",
    "validate_call_response",
    "validate_source_evidence",
]

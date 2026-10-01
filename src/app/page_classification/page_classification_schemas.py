"""Pydantic v2 response contracts for BatchLens's three classifier calls.

Python 3.11+. These models validate responses; they do not call an LLM,
classify HTML, merge responses, or assign OTHER_UNCLASSIFIED.
"""

from typing import ClassVar, Generic, Literal, Self, TypeAlias, TypeVar, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

ResponseStatus: TypeAlias = Literal["ok", "empty", "needs_review"]

MaterialEquipmentLabel: TypeAlias = Literal[
    "BILL_OF_MATERIALS",
    "EQUIPMENT_LIST",
]

ProcessOperationsLabel: TypeAlias = Literal[
    "SPECIAL_REQUIREMENTS",
    "PROCESS_FLOW_DIAGRAM",
    "SAMPLING_TESTING_PLAN",
    "FORMULATION_RECIPE",
    "BILL_OF_PACKAGING_MATERIALS",
    "MATERIAL_RECEIPT_AND_ACCEPTANCE",
    "AREA_CLEARANCE",
    "EQUIPMENT_SETUP",
    "EQUIPMENT_CLEANING_SANITIZATION",
    "EQUIPMENT_TEST",
    "EQUIPMENT_STORAGE",
    "MANUFACTURING_INSTRUCTIONS",
    "PROCESS_EXECUTION_RECORD",
    "IN_PROCESS_CONTROL",
    "ANALYTICAL_TEST_DATA",
    "WEIGHING_PRINTOUT",
    "YIELD_CALCULATION",
    "BATCH_RECONCILIATION",
    "PACKAGING_AND_LABELING",
]

DocumentSupportingLabel: TypeAlias = Literal[
    "NON_RELATED",
    "COVER_PAGE",
    "PRODUCT_BATCH_DETAILS",
    "TABLE_OF_CONTENTS",
    "DOCUMENTATION_INSTRUCTIONS",
    "EXPERIMENTAL_OBJECTIVES",
    "REFERENCE_DOCUMENTATION",
    "CHAIN_OF_IDENTITY_AND_CUSTODY",
    "INVENTORY_TRANSACTION",
    "COMMENT_LOG",
    "EXCEPTION_DEVIATION_LOG",
    "SIGNATURE_LOG",
    "SIGNATURE_APPROVAL",
    "ACKNOWLEDGEMENT",
    "BATCH_CONCLUSION",
    "BATCH_REVIEW_DISPOSITION",
    "DOCUMENT_CHANGE_HISTORY",
    "APPENDIX",
    "CERTIFICATE",
]

# Derive allowed-label vocabulary from each Literal: one source per call.
MATERIAL_EQUIPMENT_LABELS: tuple[str, ...] = get_args(MaterialEquipmentLabel)
PROCESS_OPERATIONS_LABELS: tuple[str, ...] = get_args(ProcessOperationsLabel)
DOCUMENT_SUPPORTING_LABELS: tuple[str, ...] = get_args(DocumentSupportingLabel)

LabelT = TypeVar("LabelT", bound=str)


class LabelEvidence(BaseModel, Generic[LabelT]):
    """One source-grounded justification; source matching is a separate check."""

    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")

    label: LabelT
    quote: str = Field(
        min_length=1,
        max_length=240,
        description=(
            "Short exact excerpt from this page's readable HTML text supporting "
            "the label. Decode HTML entities and collapse whitespace only. "
            "Do not paraphrase, translate, invent, or join distant passages."
        ),
    )
    reason: str = Field(
        min_length=1,
        max_length=240,
        description=(
            "One short sentence explaining which label criterion the quoted "
            "content and its local structure satisfy. Not a reasoning transcript."
        ),
    )
    element_id: str | None = Field(
        min_length=1,
        max_length=256,
        description=(
            "Exact unmodified value from id, data-node-id, data-element-id, "
            "or data-table-id on the smallest identifiable element containing "
            "the complete quote, or its nearest identifiable ancestor; null "
            "when no suitable identifier exists. Never invent, repair, or "
            "convert an identifier, selector, or page number."
        ),
    )

    @field_validator("quote", "reason", "element_id")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise PydanticCustomError("blank_evidence", "Evidence text cannot be blank")
        return value


class _PageClassificationResponse(BaseModel, Generic[LabelT]):
    """Internal shared contract; use one of the three concrete models below."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    LABEL_ORDER: ClassVar[tuple[str, ...]] = ()

    labels: list[LabelT] = Field(
        description=(
            "All supported labels from this call's allowed set, with no "
            "duplicates, in any order. An empty list is allowed."
        ),
    )
    status: ResponseStatus = Field(
        description=(
            "ok: assessable content, including no matching label in this call; "
            "empty: no content beyond recurring boilerplate, requiring labels=[]; "
            "needs_review: evidence cannot be reliably assessed; retain any "
            "independently supported labels."
        ),
    )
    evidence: list[LabelEvidence[LabelT]] = Field(
        description=(
            "Exactly one evidence item per returned label, in any order. "
            "Associate each item by its own label field. No missing or extra "
            "items. Use [] when labels=[]."
        ),
    )

    @model_validator(mode="after")
    def enforce_response_rules(self) -> Self:
        """Reject contract violations without silently repairing the response."""
        if len(self.labels) != len(set(self.labels)):
            raise PydanticCustomError(
                "duplicate_labels",
                "labels must not contain duplicates",
            )

        if self.status == "empty" and self.labels:
            raise PydanticCustomError(
                "empty_status_with_labels",
                "status='empty' requires labels=[]",
            )

        evidence_labels = [item.label for item in self.evidence]
        if len(evidence_labels) != len(set(evidence_labels)):
            raise PydanticCustomError(
                "duplicate_evidence_labels",
                "evidence labels must not contain duplicates",
            )

        if set(evidence_labels) != set(self.labels):
            raise PydanticCustomError(
                "evidence_label_mismatch",
                "evidence must cover returned labels exactly once each by label",
            )

        return self


class MaterialEquipmentResponse(_PageClassificationResponse[MaterialEquipmentLabel]):
    """Call 1: materials and equipment, including both labels together."""

    LABEL_ORDER: ClassVar[tuple[str, ...]] = MATERIAL_EQUIPMENT_LABELS


class ProcessOperationsResponse(_PageClassificationResponse[ProcessOperationsLabel]):
    """Call 2: the 19 process, operations, and control labels."""

    LABEL_ORDER: ClassVar[tuple[str, ...]] = PROCESS_OPERATIONS_LABELS


class DocumentSupportingResponse(_PageClassificationResponse[DocumentSupportingLabel]):
    """Call 3: the 19 document and supporting-record labels."""

    LABEL_ORDER: ClassVar[tuple[str, ...]] = DOCUMENT_SUPPORTING_LABELS


__all__ = [
    "LabelEvidence",
    "ResponseStatus",
    "MaterialEquipmentLabel",
    "ProcessOperationsLabel",
    "DocumentSupportingLabel",
    "MATERIAL_EQUIPMENT_LABELS",
    "PROCESS_OPERATIONS_LABELS",
    "DOCUMENT_SUPPORTING_LABELS",
    "MaterialEquipmentResponse",
    "ProcessOperationsResponse",
    "DocumentSupportingResponse",
]

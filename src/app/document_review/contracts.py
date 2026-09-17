"""Immutable canonical contracts for document review."""

from collections.abc import Iterable
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.document_conversion.aws import S3Source
from app.document_conversion.contracts import Document, Reference
from app.document_jobs.contracts import Artifact, Job

RevisionId = str
ReviewStatus = Literal["NOT_REVIEWED", "IN_REVIEW", "APPROVED"]
DecisionAction = Literal["KEEP_ORIGINAL", "RESOLVED_AFTER_EDIT", "ACKNOWLEDGED_LIMITATION"]
CommittedAction = Literal["DRAFT_SAVED", "PAGE_APPROVED", "DOCUMENT_APPROVED"]
REVISION_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewError(RuntimeError):
    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class TableGeometry(ReviewModel):
    rows: int = Field(ge=0)
    columns: int = Field(ge=0)
    row: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    row_span: int | None = Field(default=None, ge=1)
    column_span: int | None = Field(default=None, ge=1)
    header: bool | None = None


class CatalogueNode(ReviewModel):
    node_id: str
    page_number: int = Field(ge=1)
    path: str
    kind: str
    baseline_text: str
    baseline_hash: str
    reference_ids: tuple[str, ...] = ()
    references: tuple[Reference, ...] = ()
    table_geometry: TableGeometry | None = None


class ReviewCatalogue(ReviewModel):
    baseline: Artifact
    nodes: tuple[CatalogueNode, ...]
    catalogue_hash: str


class RequestedChange(ReviewModel):
    node_id: str
    text: str = Field(max_length=100_000)


class TextChange(ReviewModel):
    node_id: str
    baseline: Artifact
    original_text: str
    previous_text: str
    new_text: str
    actor: str
    at: datetime
    revision_id: RevisionId = Field(pattern=REVISION_PATTERN)


class FindingDecisionRequest(ReviewModel):
    finding_id: str
    action: DecisionAction
    note: str | None = Field(default=None, max_length=2000)
    replacement: RequestedChange | None = None
    expected_region_hash: str | None = None


class FindingDecision(ReviewModel):
    action: DecisionAction
    note: str | None = None
    actor: str
    at: datetime
    revision_id: RevisionId = Field(pattern=REVISION_PATTERN)
    region_hash: str


class SuggestedReplacement(ReviewModel):
    eligible: bool = True
    node_id: str
    text: str
    expected_region_hash: str


class ReviewFinding(ReviewModel):
    """A conversion warning bound to current evidence. ``resolved`` requires a matching region hash."""

    finding_id: str
    code: str
    pages: tuple[int, ...]
    block_ids: tuple[str, ...] = ()
    node_ids: tuple[str, ...] = ()
    evidence: tuple[Reference, ...] = ()
    region_hash: str
    decision: FindingDecision | None = None
    suggested_replacement: SuggestedReplacement | None = None

    @property
    def resolved(self) -> bool:
        # A recorded decision is current only while the evidence-region hash is unchanged.
        return self.decision is not None and self.decision.region_hash == self.region_hash


class PageApproval(ReviewModel):
    content_hash: str
    actor: str
    at: datetime
    revision_id: RevisionId = Field(pattern=REVISION_PATTERN)


class PageState(ReviewModel):
    page_number: int = Field(ge=1)
    content_hash: str
    approval: PageApproval | None = None


class DocumentApproval(ReviewModel):
    revision_id: RevisionId = Field(pattern=REVISION_PATTERN)
    document_hash: str
    actor: str
    at: datetime


class ExportPointers(ReviewModel):
    html_artifact: Artifact
    json_artifact: Artifact


class ReviewRevision(ReviewModel):
    """Immutable reviewed envelope. ``document`` is the only canonical reviewed Document."""

    schema_version: str = "1.0.0"
    job_id: str
    owner: str
    revision_id: RevisionId = Field(pattern=REVISION_PATTERN)
    parent_revision_id: RevisionId | None = Field(default=None, pattern=REVISION_PATTERN)
    parent: Artifact | None = None
    generation: int = Field(ge=1)
    created_at: datetime
    actor: str
    baseline: Artifact
    accepted_source: S3Source
    raw: Artifact
    document: Document
    catalogue: ReviewCatalogue
    pages: tuple[PageState, ...]
    findings: tuple[ReviewFinding, ...]
    changes: tuple[TextChange, ...] = ()
    action: CommittedAction
    exports: ExportPointers | None = None
    document_approval: DocumentApproval | None = None

    @model_validator(mode="after")
    def parent_pair(self) -> "ReviewRevision":
        if (self.parent_revision_id is None) != (self.parent is None):
            raise ValueError("parent id and artifact must be paired")
        return self

    @property
    def status(self) -> Literal["IN_REVIEW", "APPROVED"]:
        return "APPROVED" if self.document_approval is not None else "IN_REVIEW"


class ReviewHead(ReviewModel):
    """Small authoritative pointer. It must not contain the document body."""

    job_id: str
    owner: str
    generation: int = Field(ge=1)
    revision_id: RevisionId = Field(pattern=REVISION_PATTERN)
    revision: Artifact
    baseline: Artifact
    accepted_source: S3Source
    raw: Artifact
    status: Literal["IN_REVIEW", "APPROVED"]
    document_approval: DocumentApproval | None = None
    exports: ExportPointers | None = None
    expires_at: int


class UpdateReviewBody(ReviewModel):
    expected_revision: RevisionId | None = Field(default=None, pattern=REVISION_PATTERN)
    changes: tuple[RequestedChange, ...] = ()
    decisions: tuple[FindingDecisionRequest, ...] = ()


class PageApprovalBody(ReviewModel):
    expected_revision: RevisionId = Field(pattern=REVISION_PATTERN)


class FinalApprovalBody(ReviewModel):
    expected_revision: RevisionId = Field(pattern=REVISION_PATTERN)


class ReviewState(ReviewModel):
    status: ReviewStatus
    revision_id: RevisionId | None = None
    generation: int = Field(ge=0)
    revision: ReviewRevision | None = None
    document: Document
    catalogue: ReviewCatalogue
    pages: tuple[PageState, ...]
    findings: tuple[ReviewFinding, ...]


class ReviewStore(Protocol):
    def get(self, job_id: str) -> ReviewHead | None: ...
    def publish(self, head: ReviewHead, expected_revision: RevisionId | None) -> bool: ...


class ObjectSource(Protocol):
    def read(self, artifact: Artifact) -> bytes: ...
    def put_revision(self, job_id: str, revision_id: str, body: bytes) -> Artifact: ...
    def put_export(
        self, job_id: str, revision_id: str, format: Literal["html", "json"], body: bytes
    ) -> Artifact: ...
    def download(self, artifact: Artifact, filename: str) -> str: ...
    def stream_source(self, source: S3Source) -> Iterable[bytes]: ...


class JobSource(Protocol):
    def get(self, job_id: str) -> Job | None: ...

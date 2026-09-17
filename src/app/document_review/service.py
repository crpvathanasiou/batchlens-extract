"""Ownership-first review lifecycle with immutable S3 revisions and Dynamo CAS."""

import json
import re
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid4

from pydantic import ValidationError

from app.document_conversion.contracts import Document
from app.document_jobs.contracts import Artifact, Job
from app.document_review.contracts import (
    DocumentApproval,
    ExportPointers,
    FinalApprovalBody,
    FindingDecision,
    FindingDecisionRequest,
    JobSource,
    ObjectSource,
    PageApproval,
    PageApprovalBody,
    PageState,
    RequestedChange,
    ReviewCatalogue,
    ReviewError,
    ReviewFinding,
    ReviewHead,
    ReviewRevision,
    ReviewState,
    ReviewStore,
    TextChange,
    UpdateReviewBody,
)
from app.document_review.mapping import (
    apply_changes,
    build_catalogue,
    build_findings,
    current_texts,
    document_hash,
    page_hash,
    raw_page_lookup,
    suggested_tolerance_text,
    tolerance_replacement_eligible,
)
from app.document_review.rendering import render_reviewed_html


class ReviewService:
    """Text-only review lifecycle with immutable revisions and conditional head publish.

    Page and document approval are document-review approvals only; they are not
    batch release or a 21 CFR Part 11 electronic signature. Object bytes are
    written before the CAS head publish; a lost race raises REVIEW_CONFLICT and
    does not promote the unreachable candidate.
    """

    def __init__(
        self,
        jobs: JobSource,
        store: ReviewStore,
        objects: ObjectSource,
        clock: Callable[[], float] = time.time,
        new_revision_id: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self.jobs = jobs
        self.store = store
        self.objects = objects
        self.clock = clock
        self.new_revision_id = new_revision_id

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self.clock(), UTC)

    def _owned_completed(self, job_id: str, owner: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None or job.owner != owner:
            raise ReviewError("JOB_NOT_FOUND", 404)
        if job.phase not in {"SUCCEEDED", "PARTIAL_SUCCESS"}:
            raise ReviewError("REVIEW_NOT_READY")
        if "document.json" not in job.artifacts or job.raw is None or job.source.version is None:
            raise ReviewError("REVIEW_NOT_READY")
        return job

    def _baseline(self, job: Job) -> tuple[Document, dict[str, object]]:
        try:
            document = Document.model_validate_json(
                self.objects.read(job.artifacts["document.json"])
            )
            loaded: object = json.loads(self.objects.read(cast(Artifact, job.raw)))
        except (ValidationError, ValueError, TypeError, KeyError, UnicodeDecodeError):
            raise ReviewError("INVALID_BASELINE", 422) from None
        if not isinstance(loaded, dict):
            raise ReviewError("INVALID_BASELINE", 422)
        raw = cast(dict[str, object], loaded)
        source = document.source
        expected_identity = f"s3://{job.source.bucket}/{job.source.key}"
        if (
            source.identity != expected_identity
            or (source.bucket is not None and source.bucket != job.source.bucket)
            or (source.key is not None and source.key != job.source.key)
            or (source.version is not None and source.version != job.source.version)
        ):
            raise ReviewError("INVALID_BASELINE", 422)
        page_numbers = [page.number for page in document.pages]
        if len(page_numbers) != len(set(page_numbers)):
            raise ReviewError("INVALID_BASELINE", 422)
        return document, raw

    def _read_revision(self, artifact: Artifact) -> ReviewRevision:
        try:
            return ReviewRevision.model_validate_json(self.objects.read(artifact))
        except (ValidationError, ValueError, TypeError, UnicodeDecodeError):
            raise ReviewError("INVALID_REVIEW_STATE", 409) from None

    def _current(self, job: Job) -> tuple[ReviewHead, ReviewRevision] | None:
        try:
            head = self.store.get(job.id)
        except (ValidationError, ValueError, TypeError):
            raise ReviewError("INVALID_REVIEW_STATE") from None
        if head is None:
            return None
        if (
            head.owner != job.owner
            or head.baseline != job.artifacts["document.json"]
            or head.accepted_source != job.source
            or head.raw != job.raw
        ):
            raise ReviewError("REVIEW_CONFLICT")
        revision = self._read_revision(head.revision)
        if (
            revision.job_id != job.id
            or revision.owner != job.owner
            or revision.revision_id != head.revision_id
            or revision.generation != head.generation
            or revision.baseline != head.baseline
            or revision.accepted_source != head.accepted_source
            or revision.raw != head.raw
        ):
            raise ReviewError("INVALID_REVIEW_STATE")
        return head, revision

    def _initial(
        self, job: Job
    ) -> tuple[Document, dict[str, object], tuple[PageState, ...], tuple[ReviewFinding, ...]]:
        document, raw = self._baseline(job)
        catalogue = build_catalogue(document, job.artifacts["document.json"])
        pages = tuple(
            PageState(page_number=page.number, content_hash=page_hash(document, page.number))
            for page in document.pages
        )
        findings = build_findings(document.warnings, catalogue, document, raw)
        return document, raw, pages, findings

    def get(self, job_id: str, owner: str) -> ReviewState:
        job = self._owned_completed(job_id, owner)
        current = self._current(job)
        if current is None:
            document, _, pages, findings = self._initial(job)
            catalogue = build_catalogue(document, job.artifacts["document.json"])
            return ReviewState(
                status="NOT_REVIEWED",
                generation=0,
                document=document,
                catalogue=catalogue,
                pages=pages,
                findings=findings,
            )
        head, revision = current
        return self._state(head, revision)

    @staticmethod
    def _state(head: ReviewHead, revision: ReviewRevision) -> ReviewState:
        return ReviewState(
            status=head.status,
            revision_id=head.revision_id,
            generation=head.generation,
            revision=revision,
            document=revision.document,
            catalogue=revision.catalogue,
            pages=revision.pages,
            findings=revision.findings,
        )

    def _persist(
        self,
        job: Job,
        revision: ReviewRevision,
        expected_revision: str | None,
    ) -> ReviewState:
        # Write the unique revision object first. Only a successful conditional
        # head publish makes it reachable; a lost CAS leaves it to expire.
        artifact = self.objects.put_revision(
            job.id, revision.revision_id, revision.model_dump_json(indent=2).encode()
        )
        head = ReviewHead(
            job_id=job.id,
            owner=job.owner,
            generation=revision.generation,
            revision_id=revision.revision_id,
            revision=artifact,
            baseline=revision.baseline,
            accepted_source=revision.accepted_source,
            raw=revision.raw,
            status=revision.status,
            document_approval=revision.document_approval,
            exports=revision.exports,
            expires_at=job.expires_at,
        )
        if not self.store.publish(head, expected_revision):
            raise ReviewError("REVIEW_CONFLICT")
        return self._state(head, revision)

    @staticmethod
    def _validate_requests(body: UpdateReviewBody) -> None:
        if len({change.node_id for change in body.changes}) != len(body.changes):
            raise ReviewError("INVALID_REVIEW", 422)
        if len({item.finding_id for item in body.decisions}) != len(body.decisions):
            raise ReviewError("INVALID_REVIEW", 422)

    def _decision_changes(
        self,
        requests: Iterable[FindingDecisionRequest],
        findings: tuple[ReviewFinding, ...],
        document: Document,
        catalogue: ReviewCatalogue,
    ) -> tuple[RequestedChange, ...]:
        by_id = {finding.finding_id: finding for finding in findings}
        result: list[RequestedChange] = []
        for request in requests:
            if request.replacement is None:
                continue
            finding = by_id.get(request.finding_id)
            replacement = request.replacement
            if (
                finding is None
                or request.action != "RESOLVED_AFTER_EDIT"
                or not tolerance_replacement_eligible(
                    finding,
                    replacement.node_id,
                    request.expected_region_hash,
                    document,
                    catalogue,
                )
            ):
                raise ReviewError("INVALID_REVIEW", 422)
            current = current_texts(document, catalogue)[replacement.node_id]
            if replacement.text != suggested_tolerance_text(current):
                raise ReviewError("INVALID_REVIEW", 422)
            result.append(replacement)
        return tuple(result)

    def update(self, job_id: str, owner: str, body: UpdateReviewBody) -> ReviewState:
        job = self._owned_completed(job_id, owner)
        self._validate_requests(body)
        current = self._current(job)
        if current is None:
            if body.expected_revision is not None:
                raise ReviewError("REVIEW_CONFLICT")
            document, raw, prior_pages, prior_findings = self._initial(job)
            parent_id, parent_artifact, generation = None, None, 1
        else:
            head, prior = current
            if body.expected_revision != head.revision_id:
                raise ReviewError("REVIEW_CONFLICT")
            document, raw = prior.document, self._baseline(job)[1]
            prior_pages, prior_findings = prior.pages, prior.findings
            parent_id, parent_artifact = prior.revision_id, head.revision
            generation = prior.generation + 1
        baseline = job.artifacts["document.json"]
        catalogue = build_catalogue(self._baseline(job)[0], baseline)
        decision_changes = self._decision_changes(
            body.decisions, prior_findings, document, catalogue
        )
        all_changes = body.changes + decision_changes
        if len({change.node_id for change in all_changes}) != len(all_changes):
            raise ReviewError("INVALID_REVIEW", 422)
        revision_id, at = self.new_revision_id(), self._now()
        updated, changed = apply_changes(document, catalogue, all_changes)
        findings = build_findings(updated.warnings, catalogue, updated, raw, prior_findings)
        baseline_findings = {
            finding.finding_id: finding
            for finding in build_findings(
                self._baseline(job)[0].warnings,
                catalogue,
                self._baseline(job)[0],
                raw,
            )
        }
        requested = {item.finding_id: item for item in body.decisions}
        if not set(requested) <= {finding.finding_id for finding in findings}:
            raise ReviewError("INVALID_REVIEW", 422)
        changed_nodes = set(changed)
        resolved_findings: list[ReviewFinding] = []
        for finding in findings:
            request = requested.get(finding.finding_id)
            if request is None:
                resolved_findings.append(finding)
                continue
            baseline_finding = baseline_findings.get(finding.finding_id)
            if request.action == "RESOLVED_AFTER_EDIT" and (
                baseline_finding is None or baseline_finding.region_hash == finding.region_hash
            ):
                raise ReviewError("INVALID_REVIEW", 422)
            resolved_findings.append(
                finding.model_copy(
                    update={
                        "decision": FindingDecision(
                            action=request.action,
                            note=request.note,
                            actor=owner,
                            at=at,
                            revision_id=revision_id,
                            region_hash=finding.region_hash,
                        )
                    }
                )
            )
        node_map = {node.node_id: node for node in catalogue.nodes}
        # Text edits drop that page's approval. A new DRAFT_SAVED revision has no document approval.
        pages = tuple(
            PageState(
                page_number=page.page_number,
                content_hash=page_hash(updated, page.page_number),
                approval=(
                    page.approval
                    if page.page_number
                    not in {node_map[node_id].page_number for node_id in changed_nodes}
                    and page.approval
                    and page.approval.content_hash == page_hash(updated, page.page_number)
                    else None
                ),
            )
            for page in prior_pages
        )
        changes = tuple(
            TextChange(
                node_id=node_id,
                baseline=baseline,
                original_text=node_map[node_id].baseline_text,
                previous_text=values[0],
                new_text=values[1],
                actor=owner,
                at=at,
                revision_id=revision_id,
            )
            for node_id, values in sorted(changed.items())
        )
        revision = ReviewRevision(
            job_id=job.id,
            owner=owner,
            revision_id=revision_id,
            parent_revision_id=parent_id,
            parent=parent_artifact,
            generation=generation,
            created_at=at,
            actor=owner,
            baseline=baseline,
            accepted_source=job.source,
            raw=cast(Artifact, job.raw),
            document=updated,
            catalogue=catalogue,
            pages=pages,
            findings=tuple(resolved_findings),
            changes=changes,
            action="DRAFT_SAVED",
        )
        return self._persist(job, revision, body.expected_revision)

    def approve_page(
        self, job_id: str, owner: str, page_number: int, body: PageApprovalBody
    ) -> ReviewState:
        job = self._owned_completed(job_id, owner)
        current = self._current(job)
        if current is None or current[0].revision_id != body.expected_revision:
            raise ReviewError("REVIEW_CONFLICT")
        head, prior = current
        page = next((item for item in prior.pages if item.page_number == page_number), None)
        if page is None:
            raise ReviewError("INVALID_PAGE", 422)
        if any(page_number in finding.pages and not finding.resolved for finding in prior.findings):
            raise ReviewError("REVIEW_NOT_READY")
        revision_id, at = self.new_revision_id(), self._now()
        pages = tuple(
            item.model_copy(
                update={
                    "approval": PageApproval(
                        content_hash=item.content_hash,
                        actor=owner,
                        at=at,
                        revision_id=revision_id,
                    )
                }
            )
            if item.page_number == page_number
            else item
            for item in prior.pages
        )
        revision = prior.model_copy(
            update={
                "revision_id": revision_id,
                "parent_revision_id": prior.revision_id,
                "parent": head.revision,
                "generation": prior.generation + 1,
                "created_at": at,
                "actor": owner,
                "pages": pages,
                "changes": (),
                "action": "PAGE_APPROVED",
                "document_approval": None,
                "exports": None,
            }
        )
        return self._persist(job, revision, body.expected_revision)

    def _complete_evidence(
        self, job: Job, revision: ReviewRevision, raw: dict[str, object]
    ) -> bool:
        declared = revision.document.declared_pages
        structured = {page.number for page in revision.document.pages}
        raw_pages = set(raw_page_lookup(raw).values())
        expected: set[int] = set(range(1, declared + 1)) if declared is not None else set()
        metadata: object = raw.get("DocumentMetadata")
        raw_declared: int | None = None
        if isinstance(metadata, dict):
            pages: object = cast(dict[str, object], metadata).get("Pages")
            raw_declared = pages if isinstance(pages, int) else None
        return (
            bool(expected)
            and structured == raw_pages == expected
            and (job.pages_available is None or job.pages_available == declared)
            and raw_declared == declared
        )

    def approve(self, job_id: str, owner: str, body: FinalApprovalBody) -> ReviewState:
        job = self._owned_completed(job_id, owner)
        current = self._current(job)
        if current is None or current[0].revision_id != body.expected_revision:
            raise ReviewError("REVIEW_CONFLICT")
        head, prior = current
        raw = self._baseline(job)[1]
        if not self._complete_evidence(job, prior, raw):
            raise ReviewError("REVIEW_NOT_READY")
        if any(not finding.resolved for finding in prior.findings):
            raise ReviewError("REVIEW_NOT_READY")
        if any(
            page.approval is None or page.approval.content_hash != page.content_hash
            for page in prior.pages
        ):
            raise ReviewError("REVIEW_NOT_READY")
        revision_id, at = self.new_revision_id(), self._now()
        approval = DocumentApproval(
            revision_id=revision_id,
            document_hash=document_hash(prior.document),
            actor=owner,
            at=at,
        )
        candidate = prior.model_copy(
            update={
                "revision_id": revision_id,
                "parent_revision_id": prior.revision_id,
                "parent": head.revision,
                "generation": prior.generation + 1,
                "created_at": at,
                "actor": owner,
                "changes": (),
                "action": "DOCUMENT_APPROVED",
                "document_approval": approval,
                "exports": None,
            }
        )
        html = self.objects.put_export(
            job.id, revision_id, "html", render_reviewed_html(candidate).encode()
        )
        # The JSON export is itself a complete approved envelope. The final immutable
        # review.json adds both export pointers after these candidate exports exist.
        json_export = self.objects.put_export(
            job.id, revision_id, "json", candidate.model_dump_json(indent=2).encode()
        )
        revision = candidate.model_copy(
            update={"exports": ExportPointers(html_artifact=html, json_artifact=json_export)}
        )
        return self._persist(job, revision, body.expected_revision)

    def _historical(self, job: Job, revision_id: str) -> ReviewRevision:
        current = self._current(job)
        if current is None:
            raise ReviewError("EXPORT_NOT_FOUND", 404)
        _, revision = current
        remaining = revision.generation
        while True:
            if revision.revision_id == revision_id:
                return revision
            if revision.parent is None or revision.parent_revision_id is None or remaining <= 1:
                raise ReviewError("EXPORT_NOT_FOUND", 404)
            parent = self._read_revision(revision.parent)
            if (
                parent.revision_id != revision.parent_revision_id
                or parent.generation != revision.generation - 1
                or parent.job_id != job.id
                or parent.owner != job.owner
                or parent.baseline != job.artifacts["document.json"]
            ):
                raise ReviewError("INVALID_REVIEW_STATE")
            revision, remaining = parent, remaining - 1

    def export(
        self, job_id: str, owner: str, revision_id: str, format: Literal["html", "json"]
    ) -> str:
        job = self._owned_completed(job_id, owner)
        revision = self._historical(job, revision_id)
        if (
            revision.action != "DOCUMENT_APPROVED"
            or revision.document_approval is None
            or revision.document_approval.revision_id != revision.revision_id
            or revision.exports is None
        ):
            raise ReviewError("EXPORT_NOT_FOUND", 404)
        artifact = (
            revision.exports.html_artifact if format == "html" else revision.exports.json_artifact
        )
        return self.objects.download(artifact, f"reviewed-document.{format}")

    def source(self, job_id: str, owner: str) -> tuple[Iterable[bytes], str]:
        job = self._owned_completed(job_id, owner)
        leaf = job.filename.replace("\\", "/").split("/")[-1].strip("'\"")
        safe = re.sub(r"[^A-Za-z0-9._() -]", "_", leaf)[:180].strip(". ")
        return self.objects.stream_source(job.source), safe or "source.pdf"

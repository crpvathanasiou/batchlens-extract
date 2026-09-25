"""Save-draft fingerprinting and committed-revision chain helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from app.document_jobs.contracts import Artifact, Job
from app.document_review.contracts import (
    SAVE_FINGERPRINT_VERSION,
    FindingDecisionRequest,
    ReviewError,
    ReviewRevision,
    UpdateReviewBody,
)

FINGERPRINT_SCHEMA = "batchlens.save-draft.fingerprint.v1"


def save_request_fingerprint(job_id: str, actor: str, body: UpdateReviewBody) -> str:
    """SHA-256 of the canonical Save request. Operation ID is the lookup key, not material."""

    material = {
        "actor": actor,
        "changes": [
            {"node_id": change.node_id, "text": change.text}
            for change in sorted(body.changes, key=lambda item: item.node_id)
        ],
        "decisions": [
            _decision_material(item)
            for item in sorted(body.decisions, key=lambda item: item.finding_id)
        ],
        "expected_revision": body.expected_revision,
        "job_id": job_id,
        "schema": FINGERPRINT_SCHEMA,
    }
    canonical = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decision_material(item: FindingDecisionRequest) -> dict[str, object]:
    replacement: dict[str, str] | None
    if item.replacement is None:
        replacement = None
    else:
        replacement = {"node_id": item.replacement.node_id, "text": item.replacement.text}
    return {
        "action": item.action,
        "expected_region_hash": item.expected_region_hash,
        "finding_id": item.finding_id,
        "note": item.note,
        "replacement": replacement,
    }


def load_committed_chain(
    job: Job,
    head_revision: ReviewRevision,
    read_revision: Callable[[Artifact], ReviewRevision],
) -> tuple[ReviewRevision, ...]:
    """Walk the published parent chain from a fixed head snapshot.

    Completes the full retained generation count. Broken, cyclic, or duplicate
    operation history is invalid and is not treated as absence.
    """

    collected: list[ReviewRevision] = []
    seen: set[str] = set()
    revision = head_revision
    expected_generation = head_revision.generation
    while expected_generation >= 1:
        _check_revision_context(job, revision)
        if revision.generation != expected_generation or revision.revision_id in seen:
            raise ReviewError("INVALID_REVIEW_STATE")
        seen.add(revision.revision_id)
        collected.append(revision)
        if expected_generation == 1:
            if revision.parent is not None or revision.parent_revision_id is not None:
                raise ReviewError("INVALID_REVIEW_STATE")
            break
        if revision.parent is None or revision.parent_revision_id is None:
            raise ReviewError("INVALID_REVIEW_STATE")
        parent = read_revision(revision.parent)
        if (
            parent.revision_id != revision.parent_revision_id
            or parent.generation != revision.generation - 1
        ):
            raise ReviewError("INVALID_REVIEW_STATE")
        revision = parent
        expected_generation -= 1
    else:
        raise ReviewError("INVALID_REVIEW_STATE")
    chain = tuple(collected)
    _check_operation_metadata(chain)
    return chain


def find_committed_save(
    chain: tuple[ReviewRevision, ...],
    job_id: str,
    actor: str,
    operation_id: str,
) -> ReviewRevision | None:
    for revision in chain:
        operation = revision.save_operation
        if (
            revision.action == "DRAFT_SAVED"
            and operation is not None
            and revision.job_id == job_id
            and revision.actor == actor
            and operation.operation_id == operation_id
        ):
            return revision
    return None


def _check_revision_context(job: Job, revision: ReviewRevision) -> None:
    if (
        revision.job_id != job.id
        or revision.owner != job.owner
        or revision.baseline != job.artifacts["document.json"]
        or revision.accepted_source != job.source
        or revision.raw != job.raw
    ):
        raise ReviewError("INVALID_REVIEW_STATE")


def _check_operation_metadata(chain: tuple[ReviewRevision, ...]) -> None:
    seen_keys: set[tuple[str, str, str]] = set()
    for revision in chain:
        operation = revision.save_operation
        if operation is None:
            continue
        if revision.action != "DRAFT_SAVED":
            raise ReviewError("INVALID_REVIEW_STATE")
        if operation.fingerprint_version != SAVE_FINGERPRINT_VERSION:
            raise ReviewError("INVALID_REVIEW_STATE")
        key = (revision.job_id, revision.actor, operation.operation_id)
        if key in seen_keys:
            raise ReviewError("INVALID_REVIEW_STATE")
        seen_keys.add(key)

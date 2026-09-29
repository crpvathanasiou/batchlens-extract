"""Read-only approved-documents registry for Stage 3 document selection (U2.1).

Discovers ``document.html`` candidates under a caller-supplied root and validates
one selected file through the Stage 2 reviewed-HTML v1 reader. Does not execute
lexical extraction, write under the root, or persist a registry index.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.lexical_extraction.contracts import ReviewedHtmlV1Input, SafeStructuredError
from app.lexical_extraction.html_reader import ReviewedHtmlReadError, open_reviewed_html

DOCUMENT_HTML_NAME: Final = "document.html"
DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 100


class ApprovedDocumentError(Exception):
    """Structured selection or discovery failure for the approved-documents registry."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        reader_code: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.reader_code = reader_code
        super().__init__(f"{code}: {message}")

    def to_structured_error(self) -> SafeStructuredError:
        return SafeStructuredError(code=self.code, message=self.message, retryable=False)


@dataclass(frozen=True, slots=True)
class ApprovedDocumentIdentity:
    """Root-relative identity for one approved reviewed-HTML candidate."""

    job_id: str
    review_revision_id: str

    @property
    def relative_html_path(self) -> str:
        return f"{self.job_id}/{self.review_revision_id}/{DOCUMENT_HTML_NAME}"


@dataclass(frozen=True, slots=True)
class ApprovedDocumentCandidate:
    """Lightweight layout metadata for one discovered ``document.html``."""

    identity: ApprovedDocumentIdentity

    @property
    def job_id(self) -> str:
        return self.identity.job_id

    @property
    def review_revision_id(self) -> str:
        return self.identity.review_revision_id

    @property
    def relative_html_path(self) -> str:
        return self.identity.relative_html_path


@dataclass(frozen=True, slots=True)
class ApprovedDocumentPage:
    """One page of discovered candidates plus pagination metadata."""

    items: tuple[ApprovedDocumentCandidate, ...]
    offset: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class SelectedApprovedDocument:
    """Validated selection: identity, resolved path, and Stage 2 HTML provenance."""

    identity: ApprovedDocumentIdentity
    html_path: Path
    reviewed_html: ReviewedHtmlV1Input


class ApprovedDocumentsRegistry:
    """Read-only discovery and selection over one approved-documents root."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()

    @property
    def root(self) -> Path:
        return self._root

    def list_candidates(
        self,
        *,
        offset: int = 0,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> ApprovedDocumentPage:
        if offset < 0:
            raise ApprovedDocumentError("INVALID_ARGUMENT", "offset must be non-negative")
        if page_size < 1:
            raise ApprovedDocumentError("INVALID_ARGUMENT", "page_size must be positive")
        if page_size > MAX_PAGE_SIZE:
            raise ApprovedDocumentError(
                "INVALID_ARGUMENT",
                f"page_size must not exceed {MAX_PAGE_SIZE}",
            )

        all_candidates = tuple(self._iter_candidates())
        page = all_candidates[offset : offset + page_size]
        return ApprovedDocumentPage(
            items=page,
            offset=offset,
            page_size=page_size,
            total=len(all_candidates),
        )

    def select(self, job_id: str, review_revision_id: str) -> SelectedApprovedDocument:
        identity = ApprovedDocumentIdentity(
            job_id=_require_safe_component(job_id, "job_id"),
            review_revision_id=_require_safe_component(
                review_revision_id,
                "review_revision_id",
            ),
        )
        html_path = self._resolve_document_path(identity)
        reviewed_html = _validate_reviewed_html(html_path)
        if (
            reviewed_html.job_id != identity.job_id
            or reviewed_html.review_revision_id != identity.review_revision_id
        ):
            raise ApprovedDocumentError(
                "IDENTITY_MISMATCH",
                "folder identity does not match reviewed HTML root provenance",
            )
        return SelectedApprovedDocument(
            identity=identity,
            html_path=html_path,
            reviewed_html=reviewed_html,
        )

    def _iter_candidates(self) -> Iterator[ApprovedDocumentCandidate]:
        if not self._root.is_dir():
            return

        for job_dir in _sorted_child_dirs(self._root):
            if not _is_safe_component(job_dir.name):
                continue
            resolved_job = _resolve_under_root(job_dir, self._root)
            if resolved_job is None:
                continue

            for revision_dir in _sorted_child_dirs(resolved_job):
                if not _is_safe_component(revision_dir.name):
                    continue
                resolved_revision = _resolve_under_root(revision_dir, self._root)
                if resolved_revision is None:
                    continue
                html_path = resolved_revision / DOCUMENT_HTML_NAME
                if not html_path.is_file():
                    continue
                resolved_html = _resolve_under_root(html_path, self._root)
                if resolved_html is None:
                    continue
                yield ApprovedDocumentCandidate(
                    identity=ApprovedDocumentIdentity(
                        job_id=job_dir.name,
                        review_revision_id=revision_dir.name,
                    )
                )

    def _resolve_document_path(self, identity: ApprovedDocumentIdentity) -> Path:
        if not self._root.is_dir():
            raise ApprovedDocumentError(
                "DOCUMENT_NOT_FOUND",
                "approved-documents root does not exist",
            )

        candidate = self._root / identity.job_id / identity.review_revision_id / DOCUMENT_HTML_NAME
        try:
            resolved = candidate.resolve(strict=False)
        except OSError as exc:
            raise ApprovedDocumentError(
                "DOCUMENT_NOT_FOUND",
                "approved document path could not be resolved",
            ) from exc

        if not _path_is_under(resolved, self._root):
            raise ApprovedDocumentError(
                "PATH_ESCAPE",
                "approved document path escapes the configured root",
            )
        if not resolved.is_file():
            raise ApprovedDocumentError(
                "DOCUMENT_NOT_FOUND",
                "approved document.html was not found",
            )
        if resolved.name != DOCUMENT_HTML_NAME:
            raise ApprovedDocumentError(
                "MALFORMED_LAYOUT",
                "approved document path must end with document.html",
            )
        # Ensure the two parent directory names still match the requested identity
        # after resolve (rejects unexpected renames via intermediate symlinks).
        if (
            resolved.parent.name != identity.review_revision_id
            or resolved.parent.parent.name != identity.job_id
        ):
            raise ApprovedDocumentError(
                "PATH_ESCAPE",
                "resolved layout no longer matches the requested identity",
            )
        return resolved


def _validate_reviewed_html(path: Path) -> ReviewedHtmlV1Input:
    reader = open_reviewed_html(path)
    try:
        for _page in reader.iter_pages():
            pass
    except ReviewedHtmlReadError as exc:
        raise ApprovedDocumentError(
            "INVALID_REVIEWED_HTML",
            _bounded_message(f"reviewed HTML rejected ({exc.code}): {exc.message}"),
            reader_code=exc.code,
        ) from exc

    if not reader.completed:
        raise ApprovedDocumentError(
            "INVALID_REVIEWED_HTML",
            "reviewed HTML read did not complete",
        )
    return reader.validated_input


def _sorted_child_dirs(directory: Path) -> list[Path]:
    try:
        children = [child for child in directory.iterdir() if child.is_dir()]
    except OSError:
        return []
    return sorted(children, key=lambda path: path.name)


def _resolve_under_root(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        return None
    if not _path_is_under(resolved, root):
        return None
    return resolved


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        return path.is_relative_to(root)
    except (OSError, ValueError):
        return False


def _is_safe_component(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    if "/" in value or "\\" in value:
        return False
    if Path(value).is_absolute():
        return False
    # Refuse Windows drive-relative forms such as "C:foo".
    if len(value) >= 2 and value[1] == ":":
        return False
    return True


def _require_safe_component(value: str, field_name: str) -> str:
    if not _is_safe_component(value):
        raise ApprovedDocumentError(
            "PATH_ESCAPE",
            f"{field_name} is not a safe single path component",
        )
    return value


def _bounded_message(message: str) -> str:
    if len(message) <= 200:
        return message
    return message[:197] + "..."

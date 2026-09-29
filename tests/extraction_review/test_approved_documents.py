"""U2.1 approved-documents registry discovery and selection."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any, cast

import pytest

from app.extraction_review.approved_documents import (
    DOCUMENT_HTML_NAME,
    MAX_PAGE_SIZE,
    ApprovedDocumentError,
    ApprovedDocumentsRegistry,
)
from app.lexical_extraction.html_reader import open_reviewed_html

REVISION_A = "00000000-0000-4000-8000-00000000000a"
REVISION_B = "00000000-0000-4000-8000-00000000000b"
REVISION_C = "00000000-0000-4000-8000-00000000000c"


def _root(
    *,
    version: str = "1",
    job_id: str = "job-1",
    revision_id: str = REVISION_A,
    generation: str = "4",
    status: str = "SUCCEEDED",
) -> str:
    return (
        "<!doctype html>"
        f'<html data-review-html-version="{version}" data-job-id="{job_id}" '
        f'data-review-revision-id="{revision_id}" data-review-generation="{generation}" '
        f'data-conversion-status="{status}">'
    )


def _wrap(body: str, **root_kwargs: str) -> str:
    return (
        f"{_root(**root_kwargs)}"
        '<head><meta charset="utf-8"><title>Reviewed document</title>'
        "<style>p{}</style></head><body>"
        '<header class="summary" data-generated="true"><h1>Reviewed document</h1></header>'
        f"<main>{body}</main></body></html>"
    )


def _minimal_body() -> str:
    return '<section class="page" id="source-page-1" data-page="1"></section>'


def _write_candidate(
    root: Path,
    job_id: str,
    review_revision_id: str,
    html: str,
    *,
    sibling_review_json: bool = False,
) -> Path:
    directory = root / job_id / review_revision_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / DOCUMENT_HTML_NAME
    path.write_bytes(html.encode("utf-8"))
    if sibling_review_json:
        (directory / "review.json").write_text('{"ignored": true}', encoding="utf-8")
    return path


def _registry(tmp_path: Path) -> ApprovedDocumentsRegistry:
    return ApprovedDocumentsRegistry(tmp_path)


def _snapshot_tree(root: Path) -> dict[str, tuple[int, bytes | None]]:
    """Map relative paths to (mtime_ns, content-or-None for directories)."""

    snapshot: dict[str, tuple[int, bytes | None]] = {}
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        if path.is_file():
            snapshot[relative] = (stat.st_mtime_ns, path.read_bytes())
        else:
            snapshot[relative] = (stat.st_mtime_ns, None)
    return snapshot


def test_discovery_is_deterministic_and_paginated(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    layouts = (
        ("job-b", REVISION_A),
        ("job-a", REVISION_C),
        ("job-a", REVISION_A),
        ("job-a", REVISION_B),
    )
    for job_id, revision_id in layouts:
        _write_candidate(
            root,
            job_id,
            revision_id,
            _wrap(_minimal_body(), job_id=job_id, revision_id=revision_id),
            sibling_review_json=True,
        )

    registry = _registry(root)
    page = registry.list_candidates(offset=0, page_size=2)
    assert page.total == 4
    assert page.offset == 0
    assert page.page_size == 2
    assert [(item.job_id, item.review_revision_id) for item in page.items] == [
        ("job-a", REVISION_A),
        ("job-a", REVISION_B),
    ]

    page_two = registry.list_candidates(offset=2, page_size=2)
    assert [(item.job_id, item.review_revision_id) for item in page_two.items] == [
        ("job-a", REVISION_C),
        ("job-b", REVISION_A),
    ]
    assert page.items[0].relative_html_path == f"job-a/{REVISION_A}/{DOCUMENT_HTML_NAME}"


def test_non_matching_layout_is_excluded(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    good = _write_candidate(
        root,
        "job-1",
        REVISION_A,
        _wrap(_minimal_body(), job_id="job-1", revision_id=REVISION_A),
    )

    (root / "orphan.html").write_text("no", encoding="utf-8")
    (root / "job-only").mkdir()
    nested = root / "job-2" / REVISION_A / "extra" / DOCUMENT_HTML_NAME
    nested.parent.mkdir(parents=True)
    nested.write_text("too-deep", encoding="utf-8")
    wrong_name = root / "job-3" / REVISION_A / "document.htm"
    wrong_name.parent.mkdir(parents=True)
    wrong_name.write_text("wrong-name", encoding="utf-8")
    (root / "job-4" / REVISION_A).mkdir(parents=True)

    page = _registry(root).list_candidates()
    assert page.total == 1
    assert page.items[0].job_id == "job-1"
    assert page.items[0].review_revision_id == REVISION_A
    assert good.is_file()


def test_select_returns_stage2_validated_provenance(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    html = _wrap(_minimal_body(), job_id="job-1", revision_id=REVISION_A)
    path = _write_candidate(
        root,
        "job-1",
        REVISION_A,
        html,
        sibling_review_json=True,
    )
    expected_sha = hashlib.sha256(html.encode("utf-8")).hexdigest()

    selected = _registry(root).select("job-1", REVISION_A)
    assert selected.identity.job_id == "job-1"
    assert selected.identity.review_revision_id == REVISION_A
    assert selected.html_path == path.resolve()
    assert selected.reviewed_html.html_sha256 == expected_sha
    assert selected.reviewed_html.job_id == "job-1"
    assert selected.reviewed_html.review_revision_id == REVISION_A
    assert selected.reviewed_html.html_contract_version == 1

    # Same identity the Stage 2 reader itself would expose.
    reader = open_reviewed_html(path)
    for _page in reader.iter_pages():
        pass
    assert selected.reviewed_html == reader.validated_input


def test_folder_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    _write_candidate(
        root,
        "folder-job",
        REVISION_A,
        _wrap(_minimal_body(), job_id="html-job", revision_id=REVISION_A),
    )
    with pytest.raises(ApprovedDocumentError, match="IDENTITY_MISMATCH") as job_exc:
        _registry(root).select("folder-job", REVISION_A)
    assert job_exc.value.code == "IDENTITY_MISMATCH"

    _write_candidate(
        root,
        "job-2",
        REVISION_B,
        _wrap(_minimal_body(), job_id="job-2", revision_id=REVISION_A),
    )
    with pytest.raises(ApprovedDocumentError, match="IDENTITY_MISMATCH") as rev_exc:
        _registry(root).select("job-2", REVISION_B)
    assert rev_exc.value.code == "IDENTITY_MISMATCH"


def test_malformed_html_is_rejected_through_selection(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    _write_candidate(
        root,
        "job-1",
        REVISION_A,
        _wrap(_minimal_body(), version="2", job_id="job-1", revision_id=REVISION_A),
    )
    with pytest.raises(ApprovedDocumentError) as exc_info:
        _registry(root).select("job-1", REVISION_A)
    assert exc_info.value.code == "INVALID_REVIEWED_HTML"
    assert exc_info.value.reader_code == "UNSUPPORTED_HTML_VERSION"
    structured = exc_info.value.to_structured_error()
    assert structured.code == "INVALID_REVIEWED_HTML"
    assert structured.retryable is False


def test_missing_file_and_path_traversal_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    _write_candidate(
        root,
        "job-1",
        REVISION_A,
        _wrap(_minimal_body(), job_id="job-1", revision_id=REVISION_A),
    )
    registry = _registry(root)

    with pytest.raises(ApprovedDocumentError) as missing:
        registry.select("job-1", REVISION_B)
    assert missing.value.code == "DOCUMENT_NOT_FOUND"

    for job_id, revision_id in (
        ("..", REVISION_A),
        ("job-1", ".."),
        ("job-1/../job-2", REVISION_A),
        ("job-1", f"../{REVISION_A}"),
        ("", REVISION_A),
        ("job-1", ""),
    ):
        with pytest.raises(ApprovedDocumentError) as escaped:
            registry.select(job_id, revision_id)
        assert escaped.value.code == "PATH_ESCAPE"


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_html = outside / DOCUMENT_HTML_NAME
    outside_html.write_bytes(
        _wrap(_minimal_body(), job_id="job-1", revision_id=REVISION_A).encode("utf-8")
    )

    target_dir = root / "job-1" / REVISION_A
    target_dir.mkdir(parents=True)
    link = target_dir / DOCUMENT_HTML_NAME
    try:
        link.symlink_to(outside_html)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    # Escaping symlink must not appear in discovery.
    page = _registry(root).list_candidates()
    assert page.total == 0

    with pytest.raises(ApprovedDocumentError) as exc_info:
        _registry(root).select("job-1", REVISION_A)
    assert exc_info.value.code == "PATH_ESCAPE"


def test_listing_does_not_parse_or_load_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    _write_candidate(
        root,
        "job-1",
        REVISION_A,
        _wrap(_minimal_body(), job_id="job-1", revision_id=REVISION_A),
    )

    def _fail_open(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("listing must not open reviewed HTML")

    monkeypatch.setattr(
        "app.extraction_review.approved_documents.open_reviewed_html",
        _fail_open,
    )
    opened: list[Path] = []
    original_open = cast(Callable[..., IO[Any]], Path.open)

    def _track_open(self: Path, *args: Any, **kwargs: Any) -> IO[Any]:
        opened.append(self)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _track_open)

    page = _registry(root).list_candidates()
    assert page.total == 1
    assert not any(path.name == DOCUMENT_HTML_NAME for path in opened)


def test_registry_creates_no_files_under_root(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    _write_candidate(
        root,
        "job-1",
        REVISION_A,
        _wrap(_minimal_body(), job_id="job-1", revision_id=REVISION_A),
        sibling_review_json=True,
    )
    before = _snapshot_tree(root)
    registry = _registry(root)

    registry.list_candidates()
    registry.select("job-1", REVISION_A)
    with pytest.raises(ApprovedDocumentError):
        registry.select("missing", REVISION_A)

    after = _snapshot_tree(root)
    assert after == before
    assert not any(root.rglob("*.index"))
    assert not (root / "registry.json").exists()
    assert list(tmp_path.iterdir()) == [root]


def test_page_size_maximum_is_enforced(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    with pytest.raises(ApprovedDocumentError, match="INVALID_ARGUMENT") as exc_info:
        _registry(root).list_candidates(page_size=MAX_PAGE_SIZE + 1)
    assert exc_info.value.code == "INVALID_ARGUMENT"


def test_directory_symlink_escape_is_excluded(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    outside = tmp_path / "outside-job" / REVISION_A
    outside.mkdir(parents=True)
    (outside / DOCUMENT_HTML_NAME).write_bytes(
        _wrap(_minimal_body(), job_id="outside-job", revision_id=REVISION_A).encode("utf-8")
    )
    link = root / "outside-job"
    try:
        link.symlink_to(outside.parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink creation unavailable: {exc}")

    # On platforms where the symlink resolves outside the root, exclude it.
    page = _registry(root).list_candidates()
    assert page.total == 0
    with pytest.raises(ApprovedDocumentError) as exc_info:
        _registry(root).select("outside-job", REVISION_A)
    assert exc_info.value.code in {"PATH_ESCAPE", "DOCUMENT_NOT_FOUND"}


def test_absolute_path_components_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    registry = _registry(root)
    absolute = os.path.abspath(os.sep)
    with pytest.raises(ApprovedDocumentError) as exc_info:
        registry.select(absolute, REVISION_A)
    assert exc_info.value.code == "PATH_ESCAPE"

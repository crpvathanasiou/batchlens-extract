"""Pure deterministic document-review mapping."""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from typing import Any, cast

from app.document_conversion.contracts import Cell, Content, Document, Element, Reference, Warning
from app.document_jobs.contracts import Artifact
from app.document_review.contracts import (
    CatalogueNode,
    RequestedChange,
    ReviewCatalogue,
    ReviewError,
    ReviewFinding,
    SuggestedReplacement,
    TableGeometry,
)


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def document_hash(document: Document) -> str:
    return canonical_hash(document.model_dump(mode="json"))


def page_hash(document: Document, page_number: int) -> str:
    page = next((page for page in document.pages if page.number == page_number), None)
    if page is None:
        raise ReviewError("INVALID_PAGE", 422)
    return canonical_hash(page.model_dump(mode="json"))


# Isolated detector abbreviation only. Does not match "tolerance" or "tolerable".
_TOLER_ABBREV = re.compile(r"\btoler\.?(?!\w)", re.IGNORECASE)


def suggested_tolerance_text(text: str) -> str:
    """Canonical eligible suggestion: expand isolated Toler/Toler. then replace the single +."""
    return _TOLER_ABBREV.sub("Tolerance", text, count=1).replace("+", "±", 1)


def _node_id(baseline: Artifact, page_number: int, path: str) -> str:
    # Derived from the pinned baseline, physical page, and structural path so IDs
    # survive text edits and cannot be assigned by the client.
    return (
        "node_"
        + hash_text("\0".join((baseline.key, baseline.version, str(page_number), path)))[:32]
    )


def _geometry(content: Content, parent: Element | None) -> TableGeometry | None:
    if isinstance(content, Cell):
        return TableGeometry(
            rows=parent.rows if parent else 0,
            columns=parent.columns if parent else 0,
            row=content.row,
            column=content.column,
            row_span=content.row_span,
            column_span=content.column_span,
            header=content.header,
        )
    if isinstance(content, Element) and (content.cells or content.rows or content.columns):
        return TableGeometry(rows=content.rows, columns=content.columns)
    return None


def _node(
    baseline: Artifact,
    page_number: int,
    path: str,
    kind: str,
    content: Content,
    parent: Element | None = None,
) -> CatalogueNode:
    return CatalogueNode(
        node_id=_node_id(baseline, page_number, path),
        page_number=page_number,
        path=path,
        kind=kind,
        baseline_text=content.text,
        baseline_hash=hash_text(content.text),
        reference_ids=tuple(reference.block_id for reference in content.references),
        references=content.references,
        table_geometry=_geometry(content, parent),
    )


def _element_nodes(
    baseline: Artifact, page_number: int, path: str, element: Element
) -> Iterable[CatalogueNode]:
    yield _node(baseline, page_number, path, element.kind, element)
    for index, child in enumerate(element.children):
        yield from _element_nodes(baseline, page_number, f"{path}.children[{index}]", child)
    for index, cell in enumerate(element.cells):
        yield _node(baseline, page_number, f"{path}.cells[{index}]", "TABLE_CELL", cell, element)
    for index, title in enumerate(element.titles):
        yield _node(baseline, page_number, f"{path}.titles[{index}]", "TITLE", title, element)
    for index, footer in enumerate(element.footers):
        yield _node(baseline, page_number, f"{path}.footers[{index}]", "FOOTER", footer, element)


def build_catalogue(document: Document, baseline: Artifact) -> ReviewCatalogue:
    nodes = tuple(
        node
        for page in document.pages
        for index, element in enumerate(page.elements)
        for node in _element_nodes(
            baseline, page.number, f"pages[{page.number}].elements[{index}]", element
        )
    )
    return ReviewCatalogue(
        baseline=baseline,
        nodes=nodes,
        catalogue_hash=canonical_hash([node.model_dump(mode="json") for node in nodes]),
    )


def _replace_content(
    content: Content, page_number: int, path: str, by_location: dict[tuple[int, str], str]
) -> Content:
    update: dict[str, Any] = {}
    location = (page_number, path)
    if location in by_location:
        update["text"] = by_location[location]
    if isinstance(content, Element):
        update["children"] = tuple(
            _replace_content(child, page_number, f"{path}.children[{index}]", by_location)
            for index, child in enumerate(content.children)
        )
        update["cells"] = tuple(
            _replace_content(cell, page_number, f"{path}.cells[{index}]", by_location)
            for index, cell in enumerate(content.cells)
        )
        update["titles"] = tuple(
            _replace_content(title, page_number, f"{path}.titles[{index}]", by_location)
            for index, title in enumerate(content.titles)
        )
        update["footers"] = tuple(
            _replace_content(footer, page_number, f"{path}.footers[{index}]", by_location)
            for index, footer in enumerate(content.footers)
        )
    return content.model_copy(update=update)


def current_texts(document: Document, catalogue: ReviewCatalogue) -> dict[str, str]:
    # Re-cataloguing with the same baseline preserves IDs and reads current text.
    current = build_catalogue(document, catalogue.baseline)
    return {
        expected.node_id: actual.baseline_text
        for expected, actual in zip(catalogue.nodes, current.nodes, strict=True)
    }


def apply_changes(
    document: Document,
    catalogue: ReviewCatalogue,
    changes: Iterable[RequestedChange],
) -> tuple[Document, dict[str, tuple[str, str]]]:
    """Replace catalogue-addressed text only.

    Structure, IDs, geometry, and references stay unchanged.
    """
    supplied = tuple(changes)
    if len({change.node_id for change in supplied}) != len(supplied):
        raise ReviewError("INVALID_REVIEW", 422)
    known = {node.node_id: node for node in catalogue.nodes}
    if any(change.node_id not in known for change in supplied):
        raise ReviewError("INVALID_REVIEW", 422)
    before = current_texts(document, catalogue)
    locations = {
        (known[change.node_id].page_number, known[change.node_id].path): change.text
        for change in supplied
    }
    pages = tuple(
        page.model_copy(
            update={
                "elements": tuple(
                    _replace_content(
                        element,
                        page.number,
                        f"pages[{page.number}].elements[{index}]",
                        locations,
                    )
                    for index, element in enumerate(page.elements)
                )
            }
        )
        for page in document.pages
    )
    changed = {
        change.node_id: (before[change.node_id], change.text)
        for change in supplied
        if before[change.node_id] != change.text
    }
    return document.model_copy(update={"pages": pages}), changed


def raw_page_lookup(raw: dict[str, object]) -> dict[str, int]:
    result: dict[str, int] = {}
    blocks: object = raw.get("Blocks", ())
    if isinstance(blocks, list):
        for value in cast(list[object], blocks):
            if isinstance(value, dict):
                block = cast(dict[str, object], value)
                block_id, page = block.get("Id"), block.get("Page")
                if isinstance(block_id, str) and isinstance(page, int) and page >= 1:
                    result[block_id] = page
    return result


def _finding_identity(warning: Warning) -> str:
    return canonical_hash(
        {
            "code": warning.code,
            "block_ids": sorted(warning.block_ids),
            "provider_pages": sorted(warning.pages),
        }
    )


def build_findings(
    warnings: Iterable[Warning],
    catalogue: ReviewCatalogue,
    document: Document,
    raw: dict[str, object],
    previous: Iterable[ReviewFinding] = (),
) -> tuple[ReviewFinding, ...]:
    node_by_block: dict[str, set[str]] = {}
    refs_by_block: dict[str, Reference] = {}
    for node in catalogue.nodes:
        for reference in node.references:
            node_by_block.setdefault(reference.block_id, set()).add(node.node_id)
            refs_by_block.setdefault(reference.block_id, reference)
    texts = current_texts(document, catalogue)
    raw_pages = raw_page_lookup(raw)
    previous_by_id = {finding.finding_id: finding for finding in previous}
    ordinals: Counter[str] = Counter()
    result: list[ReviewFinding] = []
    for warning in warnings:
        identity = _finding_identity(warning)
        ordinal = ordinals[identity]
        ordinals[identity] += 1
        finding_id = "finding_" + hash_text(f"{identity}\0{ordinal}")[:32]
        node_ids = tuple(
            sorted(
                {
                    node_id
                    for block_id in warning.block_ids
                    for node_id in node_by_block.get(block_id, ())
                }
            )
        )
        pages = set(warning.pages)
        pages.update(raw_pages[x] for x in warning.block_ids if x in raw_pages)
        evidence = tuple(
            refs_by_block[block_id] for block_id in warning.block_ids if block_id in refs_by_block
        )
        region_hash = canonical_hash(
            {
                "nodes": [(node_id, texts[node_id]) for node_id in node_ids],
                "blocks": sorted(warning.block_ids),
                "pages": sorted(pages),
            }
        )
        prior = previous_by_id.get(finding_id)
        candidates = [
            (node_id, texts[node_id])
            for node_id in node_ids
            if texts[node_id].count("+") == 1 and "±" not in texts[node_id]
        ]
        suggestion = None
        if warning.code == "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY" and len(candidates) == 1:
            node_id, text = candidates[0]
            if sum(texts[item].count("+") for item in node_ids) == 1:
                suggestion = SuggestedReplacement(
                    node_id=node_id,
                    text=suggested_tolerance_text(text),
                    expected_region_hash=region_hash,
                )
        # Preserve the audit record. ReviewFinding.resolved rejects it when the
        # current evidence-region hash no longer matches.
        decision = prior.decision if prior else None
        result.append(
            ReviewFinding(
                finding_id=finding_id,
                code=warning.code,
                pages=tuple(sorted(pages)),
                block_ids=warning.block_ids,
                node_ids=node_ids,
                evidence=evidence,
                region_hash=region_hash,
                decision=decision,
                suggested_replacement=suggestion,
            )
        )
    return tuple(result)


def tolerance_replacement_eligible(
    finding: ReviewFinding,
    node_id: str,
    expected_region_hash: str | None,
    document: Document,
    catalogue: ReviewCatalogue,
) -> bool:
    if (
        finding.code != "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY"
        or finding.region_hash != expected_region_hash
        or node_id not in finding.node_ids
    ):
        return False
    text = current_texts(document, catalogue)[node_id]
    return text.count("+") == 1 and "±" not in text

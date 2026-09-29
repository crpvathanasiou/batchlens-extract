"""Render one reviewed-HTML page with lexical finding marks.

Spans are Unicode code points in the source-node text, matching Stage 2
``CharSpan`` indexing. ``<br>`` counts as one newline, the same way the reviewed
HTML reader builds block text. This module does not convert browser UTF-16 offsets.
"""

from __future__ import annotations

import html
from html.parser import HTMLParser

from pydantic import BaseModel, ConfigDict, Field

_SOURCE_TAGS = frozenset({"p", "h2", "h3", "h4", "td", "th", "footer"})


class PageHighlight(BaseModel):
    """One saved lexical span to mark inside a source node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=1)
    category_class: str = Field(min_length=1)


class _Atom:
    __slots__ = ("kind", "text")

    def __init__(self, kind: str, text: str) -> None:
        self.kind = kind
        self.text = text


def render_reviewed_page_html(
    document_html: str,
    page_number: int,
    highlights: tuple[PageHighlight, ...],
) -> str | None:
    """Return one ``section.page`` with finding marks, or None when that page is absent."""

    by_node: dict[str, list[PageHighlight]] = {}
    for highlight in highlights:
        if highlight.end_char <= highlight.start_char:
            continue
        by_node.setdefault(highlight.node_id, []).append(highlight)
    parser = _PageRenderer(page_number, by_node)
    parser.feed(document_html)
    parser.close()
    if not parser.found:
        return None
    return "".join(parser.out)


class _PageRenderer(HTMLParser):
    def __init__(self, page_number: int, highlights: dict[str, list[PageHighlight]]) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.found = False
        self._page_number = str(page_number)
        self._highlights = highlights
        self._capturing = False
        self._depth = 0
        self._in_node = False
        self._node_tag = ""
        self._node_id = ""
        self._parts: list[_Atom] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        pairs = _pairs(attrs)
        attr_map = dict(pairs)
        if tag == "section" and _is_page_section(attr_map):
            if not self._capturing and attr_map.get("data-page") == self._page_number:
                self._capturing = True
                self.found = True
                self._depth = 1
                self._emit_start(tag, pairs)
                return
            if self._capturing:
                self._depth += 1
                self._emit_start(tag, pairs)
            return
        if not self._capturing:
            return
        if tag == "section":
            self._depth += 1
        if self._in_node:
            if tag == "br":
                self._parts.append(_Atom("br", ""))
            return
        node_id = attr_map.get("data-node-id", "")
        if tag in _SOURCE_TAGS and node_id:
            self._in_node = True
            self._node_tag = tag
            self._node_id = node_id
            self._parts = []
            self._emit_start(tag, pairs)
            return
        self._emit_start(tag, pairs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.handle_starttag(tag, attrs)
            return
        super().handle_startendtag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if not self._capturing:
            return
        if self._in_node:
            if tag != self._node_tag:
                return
            spans = self._highlights.get(self._node_id, [])
            self.out.append(_render_node_inner(self._parts, spans))
            self.out.append(f"</{tag}>")
            self._in_node = False
            self._node_tag = ""
            self._node_id = ""
            self._parts = []
            return
        self.out.append(f"</{tag}>")
        if tag == "section":
            self._depth -= 1
            if self._depth <= 0:
                self._capturing = False

    def handle_data(self, data: str) -> None:
        if not self._capturing or not data:
            return
        if self._in_node:
            self._parts.append(_Atom("text", data))
            return
        self.out.append(html.escape(data))

    def _emit_start(self, tag: str, pairs: list[tuple[str, str]]) -> None:
        self.out.append(f"<{tag}{_emit_attributes(pairs)}>")


def _pairs(attrs: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
    return [(key, "" if value is None else value) for key, value in attrs]


def _is_page_section(attrs: dict[str, str]) -> bool:
    classes = attrs.get("class", "").split()
    return "page" in classes and bool(attrs.get("data-page", ""))


def _emit_attributes(pairs: list[tuple[str, str]]) -> str:
    return "".join(f' {key}="{html.escape(value, quote=True)}"' for key, value in pairs)


def _render_node_inner(parts: list[_Atom], highlights: list[PageHighlight]) -> str:
    atoms: list[_Atom] = []
    for part in parts:
        if part.kind == "br":
            atoms.append(part)
            continue
        atoms.extend(_Atom("char", character) for character in part.text)
    usable = [
        highlight
        for highlight in highlights
        if highlight.start_char < highlight.end_char <= len(atoms)
    ]
    if not usable:
        return _atoms_html(atoms)
    boundaries = {0, len(atoms)}
    for highlight in usable:
        boundaries.add(highlight.start_char)
        boundaries.add(highlight.end_char)
    points = sorted(boundaries)
    chunks: list[str] = []
    for start, end in zip(points, points[1:], strict=False):
        body = _atoms_html(atoms[start:end])
        covering = [
            highlight
            for highlight in usable
            if highlight.start_char <= start and highlight.end_char >= end
        ]
        if covering and body:
            finding_ids = " ".join(sorted({item.finding_id for item in covering}))
            classes = " ".join(["bl-hit", *sorted({item.category_class for item in covering})])
            chunks.append(
                "<mark "
                f'class="{classes}" '
                f'data-finding-id="{html.escape(finding_ids, quote=True)}" '
                'tabindex="-1">'
                f"{body}</mark>"
            )
        else:
            chunks.append(body)
    return "".join(chunks)


def _atoms_html(atoms: list[_Atom]) -> str:
    rendered: list[str] = []
    for atom in atoms:
        if atom.kind == "br":
            rendered.append("<br>")
        else:
            rendered.append(html.escape(atom.text))
    return "".join(rendered)

"""Focused coverage for the conservative tolerance-symbol detector."""

from app.document_conversion.contracts import Cell, Document, Element, Page, Reference, Source
from app.document_conversion.tolerance import detect_tolerance_ambiguities

SOURCE = Source(identity="synthetic-tolerance-fixture")
CODE = "POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY"


def _text_doc(text: str, page: int = 1, block_id: str = "block-1") -> Document:
    ref = Reference(block_id=block_id, page=page)
    element = Element(kind="text", text=text, references=(ref,))
    return Document(
        source=SOURCE,
        status="SUCCEEDED",
        pages=(Page(number=page, elements=(element,), reading_order="textract_layout"),),
    )


def _cell_doc(*cells: tuple[str, str]) -> Document:
    table_cells = tuple(
        Cell(
            text=text,
            references=(Reference(block_id=block_id, page=1),),
            row=index,
            column=1,
        )
        for index, (text, block_id) in enumerate(cells, start=1)
    )
    table = Element(
        kind="table",
        text="",
        references=(table_cells[0].references[0],),
        cells=table_cells,
        rows=len(table_cells),
        columns=1,
    )
    return Document(
        source=SOURCE,
        status="SUCCEEDED",
        pages=(Page(number=1, elements=(table,), reading_order="textract_layout"),),
    )


def _codes(document: Document) -> list[str]:
    return [warning.code for warning in detect_tolerance_ambiguities(document)]


def test_toler_plus_percent_is_flagged() -> None:
    assert CODE in _codes(_text_doc("Toler +0.1%"))


def test_toler_period_decimal_comma_is_flagged() -> None:
    assert CODE in _codes(_text_doc("Toler. + 1,5"))


def test_tolerance_with_explicit_plus_minus_is_not_flagged() -> None:
    assert CODE not in _codes(_text_doc("Tolerance ±0.1%"))


def test_explicit_ascii_plus_slash_minus_is_not_flagged() -> None:
    assert CODE not in _codes(_text_doc("Tolerance +/-0.1%"))


def test_explicit_spaced_ascii_plus_slash_minus_is_not_flagged() -> None:
    assert CODE not in _codes(_text_doc("Toler. + / - 0,1%"))


def test_bare_tolerance_plus_percent_is_flagged() -> None:
    assert CODE in _codes(_text_doc("Tolerance +0.1%"))


def test_asymmetric_plus_minus_range_is_not_flagged() -> None:
    assert CODE not in _codes(_text_doc("Tolerance +0.1 / -0.2"))


def test_asymmetric_plus_minus_percent_is_not_flagged() -> None:
    assert CODE not in _codes(_text_doc("Tolerance +0.1% / -0.2%"))


def test_target_plus_number_is_not_flagged() -> None:
    assert CODE not in _codes(_text_doc("Target +0.1%"))


def test_tolerable_prefix_is_not_a_cue() -> None:
    assert CODE not in _codes(_text_doc("Tolerable +0.1%"))


def test_two_toler_cells_with_distinct_block_ids_produce_two_warnings() -> None:
    warnings = detect_tolerance_ambiguities(
        _cell_doc(("Toler +0.1%", "cell-a"), ("Toler +0.1%", "cell-b"))
    )
    tol_warnings = [warning for warning in warnings if warning.code == CODE]
    assert len(tol_warnings) == 2
    assert {warning.block_ids for warning in tol_warnings} == {("cell-a",), ("cell-b",)}


def test_detection_does_not_mutate_the_document() -> None:
    document = _text_doc("Toler +0.1%")
    before = document.model_dump()
    warnings = detect_tolerance_ambiguities(document)
    assert warnings
    assert document.model_dump() == before


def test_explicit_notation_examples_do_not_mutate_the_document() -> None:
    samples = (
        "Tolerance ±0.1%",
        "Tolerance +/-0.1%",
        "Toler. + / - 0,1%",
        "Tolerance +0.1%",
        "Tolerance +0.1% / -0.2%",
    )
    for text in samples:
        document = _text_doc(text)
        before = document.model_dump()
        detect_tolerance_ambiguities(document)
        assert document.model_dump() == before
        assert document.pages[0].elements[0].text == text

"""Pure public facade: importing this package performs no AWS operations.

Textractor (amazon-textract-textractor==1.10.0) is now the active parser and
HTML renderer.  The previous custom normaliser (normalize.py) and HTML renderer
(html.py) have been retired.  The structured document.json contract
(contracts.Document) is preserved via a thin mapping in adapter.py.
"""

from app.document_conversion.adapter import (
    ConversionResult,
    convert_and_render,
    render_full_document_html,
    render_individual_pages,
)
from app.document_conversion.contracts import ConversionError, ConversionLimits, Document, Source

__all__ = [
    "ConversionError",
    "ConversionLimits",
    "ConversionResult",
    "Document",
    "Source",
    "convert_and_render",
    "render_full_document_html",
    "render_individual_pages",
]

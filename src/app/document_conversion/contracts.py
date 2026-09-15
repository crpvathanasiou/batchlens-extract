"""Versioned, AWS-independent document and evidence contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Source(Model):
    identity: str = Field(min_length=1)
    bucket: str | None = None
    key: str | None = None
    version: str | None = None
    checksum_sha256: str | None = None
    etag: str | None = None  # ETag is metadata, not necessarily a content hash.


class Box(Model):
    left: float
    top: float
    width: float
    height: float


class Point(Model):
    x: float
    y: float


class Reference(Model):
    block_id: str
    page: int | None = Field(default=None, ge=1)
    box: Box | None = None
    polygon: tuple[Point, ...] = ()
    confidence: float | None = None
    rotation_angle: float | None = None


class Warning(Model):
    code: str
    block_ids: tuple[str, ...] = ()
    pages: tuple[int, ...] = ()


class Content(Model):
    text: str = ""
    references: tuple[Reference, ...]
    selections: tuple[Literal["SELECTED", "NOT_SELECTED"], ...] = ()


class Cell(Content):
    row: int = Field(ge=1)
    column: int = Field(ge=1)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    header: bool = False
    entity_types: tuple[str, ...] = ()
    inferred_empty: bool = False


class Element(Content):
    kind: str
    children: tuple["Element", ...] = ()
    cells: tuple[Cell, ...] = ()
    titles: tuple[Content, ...] = ()
    footers: tuple[Content, ...] = ()
    rows: int = 0
    columns: int = 0


class Page(Model):
    number: int = Field(ge=1)
    elements: tuple[Element, ...]
    reading_order: Literal["textract_layout", "geometry_fallback"]


class Document(Model):
    schema_version: str = "1.0.0"
    converter_version: str = "1.0.0"
    source: Source
    status: Literal["SUCCEEDED", "PARTIAL_SUCCESS"]
    provider_model_version: str | None = None
    declared_pages: int | None = None
    pages: tuple[Page, ...]
    warnings: tuple[Warning, ...] = ()


class ConversionError(ValueError):
    """A safe code, never a provider payload or document text."""


class ConversionLimits(Model):
    max_blocks: int = Field(default=100_000, ge=1)
    max_pages: int = Field(default=200, ge=1)
    max_table_positions: int = Field(default=10_000, ge=1)
    max_relationship_depth: int = Field(default=64, ge=1, le=128)

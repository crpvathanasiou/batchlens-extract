"""Validated Textract JSON boundary; unknown provider fields stay in caller-owned raw JSON."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.document_conversion.contracts import Box, ConversionError, Point, Reference


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class BoundingBox(ProviderModel):
    left: float = Field(alias="Left")
    top: float = Field(alias="Top")
    width: float = Field(alias="Width")
    height: float = Field(alias="Height")


class ProviderPoint(ProviderModel):
    x: float = Field(alias="X")
    y: float = Field(alias="Y")


class Geometry(ProviderModel):
    box: BoundingBox | None = Field(default=None, alias="BoundingBox")
    polygon: tuple[ProviderPoint, ...] = Field(default=(), alias="Polygon")
    rotation: float | None = Field(default=None, alias="RotationAngle")


class Relationship(ProviderModel):
    kind: str = Field(alias="Type")
    ids: tuple[str, ...] = Field(default=(), alias="Ids")


class Block(ProviderModel):
    id: str = Field(alias="Id", min_length=1)
    kind: str = Field(alias="BlockType")
    page: int | None = Field(default=None, alias="Page", ge=1)
    text: str = Field(default="", alias="Text")
    confidence: float | None = Field(default=None, alias="Confidence")
    geometry: Geometry | None = Field(default=None, alias="Geometry")
    relationships: tuple[Relationship, ...] = Field(default=(), alias="Relationships")
    row: int | None = Field(default=None, alias="RowIndex", ge=1)
    column: int | None = Field(default=None, alias="ColumnIndex", ge=1)
    row_span: int = Field(default=1, alias="RowSpan", ge=1)
    column_span: int = Field(default=1, alias="ColumnSpan", ge=1)
    entity_types: tuple[str, ...] = Field(default=(), alias="EntityTypes")
    selection: Literal["SELECTED", "NOT_SELECTED"] | None = Field(
        default=None, alias="SelectionStatus"
    )

    def ids(self, *kinds: str) -> tuple[str, ...]:
        return tuple(i for r in self.relationships if r.kind in kinds for i in r.ids)

    def reference(self, page: int | None) -> Reference:
        geo = self.geometry
        return Reference(
            block_id=self.id,
            page=page,
            confidence=self.confidence,
            box=Box(**geo.box.model_dump()) if geo and geo.box else None,
            polygon=tuple(Point(x=p.x, y=p.y) for p in geo.polygon) if geo else (),
            rotation_angle=geo.rotation if geo else None,
        )


class Metadata(ProviderModel):
    pages: int | None = Field(default=None, alias="Pages", ge=1)


class ProviderWarning(ProviderModel):
    code: str = Field(alias="ErrorCode")
    pages: tuple[int, ...] = Field(default=(), alias="Pages")


class Analysis(ProviderModel):
    blocks: tuple[Block, ...] = Field(default=(), alias="Blocks")
    status: Literal["IN_PROGRESS", "SUCCEEDED", "PARTIAL_SUCCESS", "FAILED"] = Field(
        default="SUCCEEDED", alias="JobStatus"
    )
    metadata: Metadata = Field(default_factory=Metadata, alias="DocumentMetadata")
    warnings: tuple[ProviderWarning, ...] = Field(default=(), alias="Warnings")
    model_version: str | None = Field(default=None, alias="AnalyzeDocumentModelVersion")
    next_token: str | None = Field(default=None, alias="NextToken")


def parse_analysis(value: object) -> Analysis:
    try:
        return Analysis.model_validate(value)
    except ValidationError:
        raise ConversionError("INVALID_TEXTRACT_RESPONSE") from None

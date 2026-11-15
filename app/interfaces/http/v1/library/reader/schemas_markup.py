"""Page markup (pen, highlighter, shapes) of the TypeScript contract."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from app.modules.library.domain.reader_markup import (
    MAX_ID,
    MAX_POINTS,
    MAX_SHAPES,
    Markup,
    pages_to_dict,
)

from pydantic import BaseModel, ConfigDict, Field

MarkupTool = Literal["pen", "pencil", "highlighter", "rect", "ellipse", "line", "arrow"]


class MarkupShapeSchema(BaseModel):
    """A stroke or figure: points are fractions of the page, `width` of its width."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=MAX_ID)
    tool: MarkupTool
    color: str = Field(max_length=7)
    width: float
    points: list[list[float]] = Field(min_length=1, max_length=MAX_POINTS)


class MarkupBody(BaseModel):
    """`PUT /me/library/markup/{item_id}`: the whole markup; shapes by page number."""

    model_config = ConfigDict(extra="forbid")

    file_id: UUID
    pages: dict[str, list[MarkupShapeSchema]] = Field(
        default_factory=dict, max_length=MAX_SHAPES
    )


class MarkupResponse(BaseModel):
    """`Markup`: the caller's own markup of the item (empty when there is none)."""

    item_id: UUID
    file_id: UUID | None
    pages: dict[str, list[MarkupShapeSchema]]
    updated_at: datetime | None

    @classmethod
    def empty(cls, item_id: UUID) -> Self:
        """No markup yet."""
        return cls(item_id=item_id, file_id=None, pages={}, updated_at=None)

    @classmethod
    def from_entity(cls, markup: Markup) -> Self:
        """Map the stored markup."""
        return cls.model_validate(
            {
                "item_id": markup.item_id,
                "file_id": markup.file_id,
                "pages": pages_to_dict(markup.pages),
                "updated_at": markup.updated_at,
            }
        )

"""Shelf, progress, annotations and My library of the TypeScript contract."""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_items import ItemCardSchema
from app.modules.library.application.reader.annotation_data import AnnotationData
from app.modules.library.application.reader.views import (
    MeLibraryView,
    ShelfEntryView,
)
from app.modules.library.domain.enums import (
    AnnotationColor,
    AnnotationKind,
    ShelfState,
)
from app.modules.library.domain.reader_annotation import Annotation

from pydantic import BaseModel, ConfigDict, Field

Locator = dict[str, Any]


class OfflineLimits(BaseModel):
    """What one device may keep for offline reading."""

    max_items: int
    max_bytes: int


class MeLibraryResponse(BaseModel):
    """`MeLibrary`: continue reading, shelf counts and the offline limits."""

    # `continue` is a Python keyword: the field is renamed on the wire.
    model_config = ConfigDict(populate_by_name=True)

    continue_reading: list[ItemCardSchema] = Field(serialization_alias="continue")
    shelf_counts: dict[ShelfState, int]
    offline: OfflineLimits

    @classmethod
    def from_view(cls, view: MeLibraryView) -> Self:
        """Map the read model."""
        return cls(
            continue_reading=[
                ItemCardSchema.from_view(c) for c in view.continue_reading
            ],
            shelf_counts=dict(view.shelf_counts),
            offline=OfflineLimits(
                max_items=view.offline_max_items, max_bytes=view.offline_max_bytes
            ),
        )


class ShelfEntryResponse(BaseModel):
    """`ShelfEntry`: the card, the state, and `removed` for taken-down items."""

    item: ItemCardSchema
    state: ShelfState
    finished_at: datetime | None
    updated_at: datetime
    removed: bool

    @classmethod
    def from_view(cls, view: ShelfEntryView) -> Self:
        """Map the read model."""
        return cls(
            item=ItemCardSchema.from_view(view.item),
            state=view.state,
            finished_at=view.finished_at,
            updated_at=view.updated_at,
            removed=view.removed,
        )


class ShelfBody(BaseModel):
    """`PUT /me/library/shelf/{item_id}`."""

    model_config = ConfigDict(extra="forbid")

    state: ShelfState


class ProgressBody(BaseModel):
    """`PUT /me/library/progress/{item_id}`."""

    model_config = ConfigDict(extra="forbid")

    file_id: UUID
    locator: Locator
    percent: float
    client_ts: datetime
    seconds_read: int | None = None


class AnnotationResponse(BaseModel):
    """`Annotation`."""

    id: UUID
    item_id: UUID
    file_id: UUID
    kind: AnnotationKind
    locator: Locator
    quote: str | None
    note: str | None
    color: AnnotationColor
    client_id: UUID
    updated_at: datetime

    @classmethod
    def from_entity(cls, annotation: Annotation) -> Self:
        """Map the stored annotation."""
        return cls(
            id=annotation.id,
            item_id=annotation.item_id,
            file_id=annotation.file_id,
            kind=annotation.kind,
            locator=dict(annotation.locator),
            quote=annotation.quote,
            note=annotation.note,
            color=annotation.color,
            client_id=annotation.client_id,
            updated_at=annotation.updated_at,
        )


class AnnotationInput(BaseModel):
    """`AnnotationInput`."""

    model_config = ConfigDict(extra="forbid")

    client_id: UUID
    item_id: UUID
    file_id: UUID
    kind: AnnotationKind
    locator: Locator
    color: AnnotationColor
    quote: str | None = None
    note: str | None = None

    def to_data(self) -> AnnotationData:
        """The fields the use case works with."""
        return AnnotationData(
            client_id=self.client_id,
            item_id=self.item_id,
            file_id=self.file_id,
            kind=self.kind,
            locator=self.locator,
            quote=self.quote,
            note=self.note,
            color=self.color,
        )


class AnnotationPatchBody(BaseModel):
    """`AnnotationPatchBody`: only the keys that were sent are applied."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = None
    color: AnnotationColor | None = None


class AnnotationsSyncBody(BaseModel):
    """`AnnotationsSyncBody`: at most 200 changes in all."""

    model_config = ConfigDict(extra="forbid")

    upserts: list[AnnotationInput] = Field(default_factory=list)
    deletes: list[UUID] = Field(default_factory=list)


class AnnotationsSyncResponse(BaseModel):
    """`{items}`: the current state of the touched annotations."""

    items: list[AnnotationResponse]

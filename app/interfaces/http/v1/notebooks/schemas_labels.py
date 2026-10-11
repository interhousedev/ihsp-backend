"""Request and response models of the topic labels (spec 3.4, G12/G13)."""

from datetime import datetime
from typing import Self
from uuid import UUID

from app.modules.notebooks.application.list_labels import LabelListing
from app.modules.notebooks.domain.labels import (
    LABEL_EMOJI_MAX_CHARS,
    LABEL_NAME_MAX_CHARS,
    LabelOrigin,
    LabelRun,
    LabelRunStatus,
    SourceLabel,
)

from pydantic import BaseModel, Field


class LabelItemResponse(BaseModel):
    """`LabelItem`: a topic label and how many sources carry it."""

    id: UUID
    name: str
    emoji: str
    position: int
    origin: LabelOrigin
    source_count: int

    @classmethod
    def from_entity(cls, label: SourceLabel) -> Self:
        """Build from the label entity."""
        return cls(
            id=label.id,
            name=label.name,
            emoji=label.emoji,
            position=label.position,
            origin=label.origin,
            source_count=label.source_count,
        )


class LabelAutoResponse(BaseModel):
    """The state of the automatic labeling.

    `error` is the stable reason of a `failed` run (`nothing-to-label`, `provider`,
    `invalid-output`, `limit-reached`, `timeout`), else null.
    """

    status: LabelRunStatus
    finished_at: datetime | None
    error: str | None

    @classmethod
    def from_run(cls, run: LabelRun) -> Self:
        """Build from the run state."""
        return cls(status=run.status, finished_at=run.finished_at, error=run.error)


class LabelListResponse(BaseModel):
    """`GET /v1/notebooks/{id}/labels`: the labels and the auto labeling state."""

    items: list[LabelItemResponse]
    auto: LabelAutoResponse

    @classmethod
    def from_listing(cls, listing: LabelListing) -> Self:
        """Build from the use case result."""
        return cls(
            items=[LabelItemResponse.from_entity(item) for item in listing.items],
            auto=LabelAutoResponse.from_run(listing.auto),
        )


class CreateLabelBody(BaseModel):
    """POST /v1/notebooks/{id}/labels: a name of 1 to 40 characters and an emoji."""

    name: str = Field(min_length=1, max_length=LABEL_NAME_MAX_CHARS)
    emoji: str = Field(default="", max_length=LABEL_EMOJI_MAX_CHARS)


class UpdateLabelBody(BaseModel):
    """PATCH /v1/notebooks/{id}/labels/{label_id}: only the sent keys apply."""

    name: str | None = Field(
        default=None, min_length=1, max_length=LABEL_NAME_MAX_CHARS
    )
    emoji: str | None = Field(default=None, max_length=LABEL_EMOJI_MAX_CHARS)


class SetSourceLabelsBody(BaseModel):
    """PUT /v1/notebooks/{id}/sources/{sid}/labels: at most 3 labels (a typed error)."""

    label_ids: list[UUID]


class StartLabelsResponse(BaseModel):
    """POST /v1/notebooks/{id}/labels/auto: the run is queued."""

    status: LabelRunStatus

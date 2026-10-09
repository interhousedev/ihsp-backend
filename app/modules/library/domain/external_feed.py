"""Feeds and the subject-to-field map of UniLibrary (storage only: no sync runs).

A feed is a chosen slice of the catalogue (category, fields, types, languages, access
classes). The sync that would use it is not built, so a feed is only kept and
switched on or off. The field map says which UniLibrary field a lyceum subject is.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from app.modules.library.domain.enums import ExternalAccess, ExternalSource

from pydantic import BaseModel, ConfigDict, Field

LIST_MAX = 100
FEED_NAME_MAX = 120
FEED_MAX_ITEMS = 1_000_000

PositiveId = Annotated[int, Field(gt=0)]
FeedRunStatus = Literal["ok", "error"]


class FeedAction(StrEnum):
    """`POST .../feeds/{id}/{action}`; only enable and disable work without a sync."""

    DRY_RUN = "dry-run"
    RUN = "run"
    ENABLE = "enable"
    DISABLE = "disable"


class FeedParams(BaseModel):
    """The `params` jsonb of a feed (`Feed.params` of the TypeScript contract)."""

    model_config = ConfigDict(extra="forbid")

    category: Annotated[int, Field(ge=1, le=4)] = 1
    field_ids: list[PositiveId] = Field(default_factory=list, max_length=LIST_MAX)
    type_ids: list[PositiveId] = Field(default_factory=list, max_length=LIST_MAX)
    language_ids: list[PositiveId] = Field(default_factory=list, max_length=LIST_MAX)
    access: list[ExternalAccess] = Field(default_factory=list, max_length=3)


@dataclass(slots=True)
class Feed:
    """A stored feed; `estimate` and the `last_*` fields are set by a sync."""

    id: UUID
    name: str
    params: FeedParams
    max_items: int
    created_at: datetime
    updated_at: datetime
    source: ExternalSource = ExternalSource.UNILIBRARY
    enabled: bool = False
    estimate: int | None = None
    last_run_at: datetime | None = None
    last_status: FeedRunStatus | None = None
    last_count: int | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class FieldMapEntry:
    """A lyceum subject is this UniLibrary field."""

    subject_id: UUID
    external_field_id: int

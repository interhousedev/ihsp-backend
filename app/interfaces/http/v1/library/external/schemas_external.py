"""Request and response models of the UniLibrary endpoints (TS contract, doc 7.1/7.2).

Names follow `web/packages/api/src/types/library.ts`: `UniLibrarySearchResult`,
`UniLibraryTaxonomy`, `PinExternalBody`, `UniLibrarySettings`, `UniLibraryStatus`,
`Feed`, `FeedInput`, `FieldMapEntry`. Cards are `ItemCardSchema` of the catalogue.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_items import ItemCardSchema
from app.modules.library.application.external.views import (
    AccessOption,
    ExternalSearchResult,
    StatusView,
    TaxonomyView,
)
from app.modules.library.domain.enums import ExternalAccess
from app.modules.library.domain.external_feed import (
    FEED_MAX_ITEMS,
    FEED_NAME_MAX,
    Feed,
    FeedParams,
    FeedRunStatus,
    FieldMapEntry,
)
from app.modules.library.ports.external_catalog import TaxonomyEntry
from app.modules.library.ports.external_monitor import (
    BreakerState,
    CacheStatsView,
    CallRecord,
)
from app.modules.library.ports.external_settings import ExternalFlags

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

FeedName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=FEED_NAME_MAX),
]
MaxItems = Annotated[int, Field(ge=0, le=FEED_MAX_ITEMS)]


class UniLibraryAccessFilter(StrEnum):
    """`?access=` of the search; `any` sends no access filter."""

    OPEN = "open"
    PARTIAL = "partial"
    CLOSED = "closed"
    ANY = "any"

    def to_domain(self) -> ExternalAccess | None:
        """The access class to ask for, or None for any."""
        if self is UniLibraryAccessFilter.ANY:
            return None
        return ExternalAccess(self.value)


# - - - Search, record, pin, taxonomies - - -


class UniLibrarySearchResultResponse(BaseModel):
    """`UniLibrarySearchResult`: cards that are not stored."""

    items: list[ItemCardSchema]
    page: int
    total: int
    stale: bool

    @classmethod
    def from_view(cls, view: ExternalSearchResult) -> Self:
        """Build from the search result."""
        return cls(
            items=[ItemCardSchema.from_view(card) for card in view.items],
            page=view.page,
            total=view.total,
            stale=view.stale,
        )


class PinExternalBody(BaseModel):
    """`PinExternalBody`: the category decides the link of the record."""

    category: Literal[1, 2, 3, 4]


class TaxonomyEntryResponse(BaseModel):
    """A type, field or language of UniLibrary."""

    id: int
    name: str

    @classmethod
    def from_entry(cls, entry: TaxonomyEntry) -> Self:
        """Build from the entry."""
        return cls(id=entry.id, name=entry.name)


class AccessOptionResponse(BaseModel):
    """An access filter option."""

    id: UniLibraryAccessFilter
    name: str

    @classmethod
    def from_view(cls, view: AccessOption) -> Self:
        """Build from the option."""
        return cls(id=UniLibraryAccessFilter(view.id), name=view.name)


class UniLibraryTaxonomyResponse(BaseModel):
    """`UniLibraryTaxonomy`: the filters the search offers."""

    types: list[TaxonomyEntryResponse]
    fields: list[TaxonomyEntryResponse]
    languages: list[TaxonomyEntryResponse]
    access: list[AccessOptionResponse]
    enabled: bool
    """False while UniLibrary is off: the lists are then empty."""

    @classmethod
    def from_view(cls, view: TaxonomyView) -> Self:
        """Build from the taxonomy view."""
        return cls(
            enabled=view.enabled,
            types=[TaxonomyEntryResponse.from_entry(e) for e in view.types],
            fields=[TaxonomyEntryResponse.from_entry(e) for e in view.fields],
            languages=[TaxonomyEntryResponse.from_entry(e) for e in view.languages],
            access=[AccessOptionResponse.from_view(a) for a in view.access],
        )


# - - - Administration - - -


class UniLibrarySettingsBody(BaseModel):
    """`UniLibrarySettings` as sent by `PUT .../settings`."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    anonymous_cards: bool


class UniLibrarySettingsResponse(BaseModel):
    """`UniLibrarySettings`: the effective switches."""

    enabled: bool
    anonymous_cards: bool

    @classmethod
    def from_flags(cls, flags: ExternalFlags) -> Self:
        """Build from the flags."""
        return cls(enabled=flags.enabled, anonymous_cards=flags.anonymous_cards)


class FeedInputBody(BaseModel):
    """`FeedInput`: a new feed."""

    model_config = ConfigDict(extra="forbid")

    name: FeedName
    params: FeedParams
    max_items: MaxItems


class FeedPatchBody(BaseModel):
    """`Partial<FeedInput>`: only the keys that were sent are applied."""

    model_config = ConfigDict(extra="forbid")

    name: FeedName | None = None
    params: FeedParams | None = None
    max_items: MaxItems | None = None


class FeedResponse(BaseModel):
    """`Feed`."""

    id: UUID
    name: str
    enabled: bool
    params: FeedParams
    max_items: int
    estimate: int | None
    last_run_at: datetime | None
    last_status: FeedRunStatus | None
    last_count: int | None

    @classmethod
    def from_entity(cls, feed: Feed) -> Self:
        """Build from the stored feed."""
        return cls(
            id=feed.id,
            name=feed.name,
            enabled=feed.enabled,
            params=feed.params,
            max_items=feed.max_items,
            estimate=feed.estimate,
            last_run_at=feed.last_run_at,
            last_status=feed.last_status,
            last_count=feed.last_count,
        )


class FieldMapEntrySchema(BaseModel):
    """`FieldMapEntry`: this subject is that UniLibrary field."""

    subject_id: UUID
    external_field_id: Annotated[int, Field(gt=0)]

    @classmethod
    def from_entity(cls, entry: FieldMapEntry) -> Self:
        """Build from the stored entry."""
        return cls(
            subject_id=entry.subject_id, external_field_id=entry.external_field_id
        )

    def to_entity(self) -> FieldMapEntry:
        """The domain entry."""
        return FieldMapEntry(self.subject_id, self.external_field_id)


class CallRecordResponse(BaseModel):
    """One of the last calls to UniLibrary."""

    at: datetime
    ok: bool
    ms: int
    path: str

    @classmethod
    def from_record(cls, record: CallRecord) -> Self:
        """Build from the call record."""
        return cls(at=record.at, ok=record.ok, ms=record.ms, path=record.path)


class CacheStatsResponse(BaseModel):
    """Cache counters."""

    hits: int
    misses: int
    stale_served: int

    @classmethod
    def from_view(cls, view: CacheStatsView) -> Self:
        """Build from the counters."""
        return cls(hits=view.hits, misses=view.misses, stale_served=view.stale_served)


class UniLibraryStatusResponse(BaseModel):
    """`UniLibraryStatus`."""

    breaker: BreakerState
    last_calls: list[CallRecordResponse]
    cache: CacheStatsResponse
    hidden_records: list[ItemCardSchema]

    @classmethod
    def from_view(cls, view: StatusView) -> Self:
        """Build from the status view."""
        return cls(
            breaker=view.breaker,
            last_calls=[CallRecordResponse.from_record(c) for c in view.last_calls],
            cache=CacheStatsResponse.from_view(view.cache),
            hidden_records=[ItemCardSchema.from_view(c) for c in view.hidden_records],
        )

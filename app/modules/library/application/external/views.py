"""Read models of the UniLibrary area (HTTP schemas map them one to one)."""

from dataclasses import dataclass, field

from app.modules.library.application.views import ItemCardView
from app.modules.library.ports.external_catalog import TaxonomyEntry
from app.modules.library.ports.external_monitor import (
    BreakerState,
    CacheStatsView,
    CallRecord,
)


@dataclass(frozen=True, slots=True)
class ExternalSearchResult:
    """`UniLibrarySearchResult`: one page of cards, none of them stored."""

    items: tuple[ItemCardView, ...]
    page: int
    total: int
    stale: bool


@dataclass(frozen=True, slots=True)
class PinResult:
    """The card of a pinned record; `created` is False when it was pinned before."""

    card: ItemCardView
    created: bool


@dataclass(frozen=True, slots=True)
class AccessOption:
    """An access filter option: `any`, `open`, `partial` or `closed`."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class TaxonomyView:
    """`UniLibraryTaxonomy`: what the search filters offer."""

    types: tuple[TaxonomyEntry, ...]
    fields: tuple[TaxonomyEntry, ...]
    languages: tuple[TaxonomyEntry, ...]
    access: tuple[AccessOption, ...]
    stale: bool = False


@dataclass(frozen=True, slots=True)
class StatusView:
    """`UniLibraryStatus`: the admin page of the connection."""

    breaker: BreakerState
    last_calls: list[CallRecord] = field(default_factory=list)
    cache: CacheStatsView = field(default_factory=CacheStatsView)
    hidden_records: list[ItemCardView] = field(default_factory=list)

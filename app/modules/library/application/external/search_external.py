"""Search UniLibrary on demand: the server asks, the page is cached, none stored."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.modules.library.application.external.cards import ExternalCards
from app.modules.library.application.external.gate import ExternalGate
from app.modules.library.application.external.views import ExternalSearchResult
from app.modules.library.application.locale import resolve_locale
from app.modules.library.domain.enums import ExternalAccess
from app.modules.library.domain.errors import LibraryRateLimitedError
from app.modules.library.domain.external_feed import FieldMapEntry
from app.modules.library.domain.external_mapping import language_id_for_code
from app.modules.library.ports.external_catalog import ExternalCatalog, ExternalSearch
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import RateLimitedError
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.rate_limit import RateLimiter

PAGE_SIZE = 20
WINDOW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """`GET /library/external/unilibrary/search?...`; unset filters are not sent."""

    q: str | None = None
    subject_id: UUID | None = None
    field_id: int | None = None
    type_id: int | None = None
    language: str | None = None
    access: ExternalAccess | None = None
    page: int = 1
    accept_language: str | None = None


def field_for_subject(field_map: list[FieldMapEntry], subject_id: UUID) -> int | None:
    """The first UniLibrary field mapped to the subject (lowest id), if any."""
    fields = [e.external_field_id for e in field_map if e.subject_id == subject_id]
    return min(fields) if fields else None


class SearchExternal:
    """LIB-5, LIB-12: one page of live UniLibrary results as unstored cards."""

    def __init__(
        self,
        *,
        gate: ExternalGate,
        catalog: ExternalCatalog,
        uow_factory: UowFactory,
        cards: ExternalCards,
        identity: IdentityDirectory,
        rate_limiter: RateLimiter,
        clock: Clock,
        searches_per_minute: int,
    ) -> None:
        """Take the gate, the catalogue, the card builder and the per-user limit."""
        self.gate = gate
        self.catalog = catalog
        self.uow_factory = uow_factory
        self.cards = cards
        self.identity = identity
        self.rate_limiter = rate_limiter
        self.clock = clock
        self.searches_per_minute = searches_per_minute

    async def execute(self, actor: Actor, query: SearchQuery) -> ExternalSearchResult:
        """Check the flag and the user's limit, ask UniLibrary, build the cards."""
        await self.gate.ensure_enabled()
        await self._limit(actor)
        locale = await resolve_locale(self.identity, actor, query.accept_language)
        field_map: list[FieldMapEntry] | None = None
        field_id = query.field_id
        if field_id is None and query.subject_id is not None:
            async with self.uow_factory() as uow:
                field_map = await uow.external.field_map()
            field_id = field_for_subject(field_map, query.subject_id)
            if field_id is None:
                return ExternalSearchResult((), query.page, 0, False)
        page = await self.catalog.search(
            ExternalSearch(
                q=query.q,
                page=query.page,
                limit=PAGE_SIZE,
                language=locale,
                field_id=field_id,
                type_id=query.type_id,
                language_id=language_id_for_code(query.language or ""),
                access=query.access,
            )
        )
        async with self.uow_factory() as uow:
            cards = await self.cards.build(
                uow, page.records, viewer=actor, locale=locale, field_map=field_map
            )
        return ExternalSearchResult(tuple(cards), page.page, page.total, page.stale)

    async def _limit(self, actor: Actor) -> None:
        key = f"library:rl:{actor.user_id}:search"
        try:
            await self.rate_limiter.hit(
                key, limit=self.searches_per_minute, window_seconds=WINDOW_SECONDS
            )
        except RateLimitedError as error:
            retry_after = int(error.params.get("retry_after", WINDOW_SECONDS))
            resets_at = self.clock.now() + timedelta(seconds=retry_after)
            raise LibraryRateLimitedError(
                params={
                    "action": "search",
                    "limit": self.searches_per_minute,
                    "resets_at": resets_at.isoformat(),
                }
            ) from error

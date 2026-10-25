"""`ExternalCatalog` over UniLibrary: client + cache + breaker (doc 3.3).

Every read goes: fresh cache entry, else (breaker open: stale entry or
`ExternalUnavailableError`), else the source; a failure serves the stale entry
marked `stale`, or `ExternalUnavailableError` with `params.retry_after`.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TypeVar

from app.modules.library.domain.errors import ExternalUnavailableError
from app.modules.library.infrastructure.unilibrary.breaker import CircuitBreaker
from app.modules.library.infrastructure.unilibrary.cache import CacheEntry, StaleCache
from app.modules.library.infrastructure.unilibrary.client import UniLibraryClient
from app.modules.library.infrastructure.unilibrary.errors import UpstreamError
from app.modules.library.infrastructure.unilibrary.mapper import (
    map_detail,
    map_list_page,
    map_taxonomy,
)
from app.modules.library.infrastructure.unilibrary.params import (
    list_cache_key,
    list_query,
)
from app.modules.library.ports.external_catalog import (
    ExternalPage,
    ExternalRecord,
    ExternalSearch,
    ExternalTaxonomies,
)
from app.settings import LibrarySettings

import structlog
from pydantic import TypeAdapter, ValidationError

log = structlog.get_logger(__name__)

T = TypeVar("T")
RETRY_AFTER_DEFAULT = 5  # seconds to suggest after a single failure


@dataclass(frozen=True, slots=True)
class _RecordBox:
    """A record or its absence, as cached (the record page of a deleted item)."""

    record: ExternalRecord | None


_PAGE = TypeAdapter(ExternalPage)
_BOX = TypeAdapter(_RecordBox)
_TAXONOMIES = TypeAdapter(ExternalTaxonomies)


class CachedCatalog:
    """The UniLibrary implementation of the `ExternalCatalog` port."""

    def __init__(
        self,
        *,
        client: UniLibraryClient,
        cache: StaleCache,
        breaker: CircuitBreaker,
        settings: LibrarySettings,
    ) -> None:
        """Compose the pieces; TTLs and the description limit come from settings."""
        self.client = client
        self.cache = cache
        self.breaker = breaker
        self.settings = settings

    # - - - Port - - -

    async def search(self, params: ExternalSearch) -> ExternalPage:
        """A page of records matching the search."""
        query = list_query(params)

        async def fetch() -> ExternalPage:
            payload = await self.client.list_resources(query)
            return map_list_page(
                payload,
                description_max=self.settings.unilibrary_description_max,
                category=params.category,
            )

        page, stale = await self._through(
            list_cache_key(query),
            fresh_ttl=self.settings.unilibrary_cache_list_ttl,
            adapter=_PAGE,
            fetch=fetch,
        )
        return replace(page, stale=stale)

    async def get(
        self, external_id: str, *, category: int, language: str
    ) -> tuple[ExternalRecord | None, bool]:
        """The full record (None when UniLibrary no longer has it) and `stale`."""
        if not external_id.isascii() or not external_id.isdigit():
            return None, False

        async def fetch() -> _RecordBox:
            payload = await self.client.resource(external_id, language)
            if payload is None:
                return _RecordBox(None)
            record = map_detail(
                payload,
                category=category,
                description_max=self.settings.unilibrary_description_max,
            )
            return _RecordBox(record)

        box, stale = await self._through(
            f"library:ext:detail:{external_id}:{language}",
            fresh_ttl=self.settings.unilibrary_cache_detail_ttl,
            adapter=_BOX,
            fetch=fetch,
        )
        return box.record, stale

    async def taxonomies(self, language: str) -> ExternalTaxonomies:
        """Types, fields and languages for the search filters."""

        async def fetch() -> ExternalTaxonomies:
            return ExternalTaxonomies(
                types=map_taxonomy(
                    await self.client.taxonomy("resource-types"), language, category=1
                ),
                fields=map_taxonomy(
                    await self.client.taxonomy("resource-fields"), language
                ),
                languages=map_taxonomy(
                    await self.client.taxonomy("resource-languages"), language
                ),
            )

        value, stale = await self._through(
            f"library:ext:taxonomies:{language}",
            fresh_ttl=self.settings.taxonomy_cache_ttl,
            adapter=_TAXONOMIES,
            fetch=fetch,
        )
        return replace(value, stale=stale)

    # - - - Cache, breaker, fallback - - -

    async def _through(
        self,
        key: str,
        *,
        fresh_ttl: int,
        adapter: TypeAdapter[T],
        fetch: Callable[[], Awaitable[T]],
    ) -> tuple[T, bool]:
        """The value and whether it is stale; see the module docstring."""
        entry = await self.cache.get(key, fresh_ttl=fresh_ttl)
        cached = self._decode(entry, adapter)
        if cached is not None and entry is not None and entry.fresh:
            await self.cache.count_hit()
            return cached, False
        await self.cache.count_miss()
        status = await self.breaker.status()
        if status.is_open:
            return await self._stale_or_raise(cached, status.retry_after)
        try:
            value = await fetch()
        except UpstreamError as exc:
            log.warning(
                "library_unilibrary_failed",
                kind=exc.kind,
                status=exc.status,
                detail=exc.detail,
            )
            await self.breaker.record_failure(exc.retry_after)
            after = await self.breaker.status()
            return await self._stale_or_raise(
                cached, after.retry_after or RETRY_AFTER_DEFAULT
            )
        await self.breaker.record_success()
        await self.cache.put(
            key, adapter.dump_json(value).decode(), fresh_ttl=fresh_ttl
        )
        return value, False

    def _decode(self, entry: CacheEntry | None, adapter: TypeAdapter[T]) -> T | None:
        """The cached value; an entry we can no longer read counts as a miss."""
        if entry is None:
            return None
        try:
            return adapter.validate_json(entry.body)
        except ValidationError:
            log.warning("library_unilibrary_cache_unreadable")
            return None

    async def _stale_or_raise(
        self, cached: T | None, retry_after: int
    ) -> tuple[T, bool]:
        if cached is None:
            raise ExternalUnavailableError(params={"retry_after": retry_after})
        await self.cache.count_stale()
        return cached, True

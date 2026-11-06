"""McpScopeOverlayPort over the extra scopes of connectors."""

from typing import TYPE_CHECKING
from uuid import UUID

from app.interfaces.mcp.ports import McpScopeOverlayPort
from app.modules.identity.infrastructure.redis.scope_overlay_cache import (
    RedisScopeOverlayCache,
)
from app.modules.identity.ports.unit_of_work import UowFactory

if TYPE_CHECKING:
    from app.bootstrap.container import Container


class ScopeOverlayAdapter:
    """Reads `extra_scopes` through the short cache; a revoked connector has none."""

    def __init__(self, uow_factory: UowFactory, cache: RedisScopeOverlayCache) -> None:
        """Keep the identity unit of work and the cache."""
        self._uow_factory = uow_factory
        self._cache = cache

    async def extra_scopes(self, connector_id: UUID) -> frozenset[str]:
        """The extra scopes of a connector, cached for 30 seconds."""
        cached = await self._cache.get(connector_id)
        if cached is not None:
            return cached
        async with self._uow_factory() as uow:
            connector = await uow.connectors.get(connector_id)
        scopes: frozenset[str] = frozenset()
        if connector is not None and connector.revoked_at is None:
            scopes = frozenset(connector.extra_scopes)
        await self._cache.put(connector_id, scopes)
        return scopes


def build_scope_overlay(container: "Container") -> McpScopeOverlayPort | None:
    """Build the overlay over the identity tables and Redis."""
    return ScopeOverlayAdapter(
        container.identity.auth.uow_factory, RedisScopeOverlayCache(container.redis)
    )

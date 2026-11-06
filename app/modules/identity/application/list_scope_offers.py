"""GET /v1/id/me/connectors/offers: open offers of new MCP scopes (A7)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.mcp_scopes import RELEASES, scope_info


@dataclass(frozen=True, slots=True)
class ScopeOfferView:
    """An open offer for the owner; the token never leaves the notification."""

    id: UUID
    release_id: str
    server: str
    read_scopes: tuple[str, ...]
    write_scopes: tuple[str, ...]
    connector_names: tuple[str, ...]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ListScopeOffers:
    """The caller's own offers that can still be decided."""

    uow_factory: UowFactory
    clock: Clock

    async def execute(self, user_id: UUID) -> list[ScopeOfferView]:
        """Pending and unexpired, with the keys still active."""
        now = self.clock.now()
        servers = {release.id: release.server for release in RELEASES}
        async with self.uow_factory() as uow:
            offers = await uow.scope_offers.list_open_for_user(user_id, now)
            connectors = await uow.connectors.list_for_user(user_id) if offers else []
        names = {c.id: c.name for c in connectors if c.is_active(now)}
        views = []
        for offer in offers:
            server = servers.get(offer.release_id)
            if server is None:
                continue
            writes = [s for s in offer.scopes if scope_info(server, s).write]
            views.append(
                ScopeOfferView(
                    id=offer.id,
                    release_id=offer.release_id,
                    server=server,
                    read_scopes=tuple(s for s in offer.scopes if s not in writes),
                    write_scopes=tuple(writes),
                    connector_names=tuple(
                        names[c] for c in offer.connector_ids if c in names
                    ),
                    expires_at=offer.expires_at,
                )
            )
        return views

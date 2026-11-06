"""Job `identity.offer_mcp_scopes`: offer the scopes of each release once per user."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.identity.domain.connector import McpConnector
from app.modules.identity.domain.scope_offer import (
    OFFER_STATUS_PENDING,
    OFFER_TTL,
    ScopeOffer,
    new_offer_token,
)
from app.modules.identity.domain.scopes import role_may_use_server
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id
from app.shared.mcp_scopes import (
    OFFERABLE_SERVERS,
    RELEASES,
    SCOPE_NAMES_BY_SERVER,
    ScopeRelease,
    scope_info,
)
from app.shared.notifications import NotificationDraft, NotificationType

BATCH = 200


def _held(connector: McpConnector) -> set[str]:
    return {*connector.scopes, *connector.extra_scopes}


@dataclass(frozen=True, slots=True)
class OfferMcpScopes:
    """Stateless: computed from the registry; a re-run or a crash sends nothing twice.

    The offer row and its notification share one transaction, and the row is unique per
    user and release.
    """

    uow_factory: UowFactory
    clock: Clock

    async def execute(self) -> int:
        """Close overdue offers and make the missing ones; return how many were made."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            await uow.scope_offers.expire_overdue(now)
            await uow.commit()
        made = 0
        for release in RELEASES:
            if release.server in OFFERABLE_SERVERS:
                made += await self._offer_release(release, now)
        return made

    async def _offer_release(self, release: ScopeRelease, now: datetime) -> int:
        known = set(SCOPE_NAMES_BY_SERVER[release.server])
        scopes = [scope for scope in release.scopes if scope in known]
        made, after = 0, None
        while True:
            async with self.uow_factory() as uow:
                users = await uow.scope_offers.users_to_offer(
                    release.id, release.server, scopes, now, after=after, limit=BATCH
                )
            for user_id in users:
                made += await self._offer_user(release, scopes, user_id, now)
            if len(users) < BATCH:
                return made
            after = users[-1]

    async def _offer_user(
        self, release: ScopeRelease, scopes: list[str], user_id: UUID, now: datetime
    ) -> int:
        async with self.uow_factory() as uow:
            user = await uow.users.get(user_id)
            if (
                user is None
                or user.status != UserStatus.ACTIVE
                or not role_may_use_server(user.roles, release.server)
            ):
                return 0
            connectors = [
                c
                for c in await uow.connectors.list_for_user(user_id)
                if c.server == release.server
                and c.is_active(now)
                and not set(scopes) <= _held(c)
            ]
            missing = [s for s in scopes if any(s not in _held(c) for c in connectors)]
            if not missing:
                return 0
            token, token_hash = new_offer_token()
            offer = ScopeOffer(
                id=new_id(),
                user_id=user_id,
                release_id=release.id,
                scopes=missing,
                connector_ids=[c.id for c in connectors],
                status=OFFER_STATUS_PENDING,
                token_hash=token_hash,
                expires_at=now + OFFER_TTL,
            )
            if not await uow.scope_offers.add_if_new(offer):
                return 0
            uow.notify(_notification(release, offer, token, connectors))
            await uow.commit()
        return 1


def _notification(
    release: ScopeRelease,
    offer: ScopeOffer,
    token: str,
    connectors: list[McpConnector],
) -> NotificationDraft:
    writes = {s for s in offer.scopes if scope_info(release.server, s).write}
    return NotificationDraft(
        user_id=offer.user_id,
        type=NotificationType.MCP_SCOPE_OFFER,
        payload={
            "token": token,
            "release_id": release.id,
            "summary_key": release.summary_key,
            "read_scopes": [s for s in offer.scopes if s not in writes],
            "write_scopes": [s for s in offer.scopes if s in writes],
            "connector_names": [c.name for c in connectors],
            "expires_at": offer.expires_at.isoformat(),
        },
        dedupe_key=f"mcp-scopes:{release.id}:{offer.user_id}",
    )

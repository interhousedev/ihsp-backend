"""A press of "give permissions" or "don't give permissions" on an offer (A7)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.domain.audit_event import (
    CONNECTOR_SCOPE_OFFER_DECLINED,
    CONNECTOR_SCOPES_EXTENDED,
)
from app.modules.identity.domain.connector import McpConnector
from app.modules.identity.domain.scope_offer import (
    OFFER_STATUS_DECLINED,
    OFFER_STATUS_EXPIRED,
    OFFER_STATUS_GRANTED,
    DecideResult,
    ScopeDecision,
    ScopeOffer,
    hash_offer_token,
)
from app.modules.identity.domain.scopes import role_may_use_server
from app.modules.identity.ports.scope_offer_repository import ScopeOverlayCache
from app.modules.identity.ports.unit_of_work import (
    IdentityUnitOfWorkPort,
    UowFactory,
)
from app.shared.clock import Clock
from app.shared.contracts.identity import UserStatus
from app.shared.mcp_scopes import (
    OFFERABLE_SERVERS,
    RELEASES,
    SCOPE_NAMES_BY_SERVER,
    ScopeRelease,
)

import structlog

log = structlog.get_logger(__name__)


def _release(release_id: str) -> ScopeRelease | None:
    return next((r for r in RELEASES if r.id == release_id), None)


@dataclass(frozen=True, slots=True)
class DecideScopeOffer:
    """Single use, bound to the offer's user; the grant re-checks every key."""

    uow_factory: UowFactory
    clock: Clock
    overlay_cache: ScopeOverlayCache

    async def execute(self, token: str, user_id: UUID, *, grant: bool) -> ScopeDecision:
        """Decide the offer behind the token for this user.

        An unknown token and someone else's token answer the same, so a button reveals
        nothing to anyone but its owner.
        """
        async with self.uow_factory() as uow:
            offer = await uow.scope_offers.get_by_token_hash(hash_offer_token(token))
            return await self._decide(uow, offer, user_id, grant, "telegram")

    async def decide_by_id(
        self, offer_id: UUID, user_id: UUID, *, grant: bool
    ) -> ScopeDecision:
        """Decide from the signed-in connectors page; the same rules as the button."""
        async with self.uow_factory() as uow:
            offer = await uow.scope_offers.get(offer_id)
            return await self._decide(uow, offer, user_id, grant, "web")

    async def _decide(
        self,
        uow: IdentityUnitOfWorkPort,
        offer: ScopeOffer | None,
        user_id: UUID,
        grant: bool,
        via: str,
    ) -> ScopeDecision:
        now = self.clock.now()
        status = OFFER_STATUS_GRANTED if grant else OFFER_STATUS_DECLINED
        if offer is None or offer.user_id != user_id:
            return ScopeDecision(DecideResult.NOT_AVAILABLE)
        decided = await uow.scope_offers.decide(offer.id, status, now)
        if decided is None:
            # A pending read may have lost a race; only the date says it is late.
            expired = offer.status == OFFER_STATUS_EXPIRED
            late = expired or offer.expires_at <= now
            return ScopeDecision(
                DecideResult.EXPIRED if late else DecideResult.ALREADY_DECIDED
            )
        if not grant:
            uow.audit(
                make_audit(
                    CONNECTOR_SCOPE_OFFER_DECLINED,
                    user_id=user_id,
                    release_id=offer.release_id,
                    via=via,
                )
            )
            await uow.commit()
            return ScopeDecision(DecideResult.DECLINED)
        names = await self._grant(uow, decided, via)
        await uow.commit()
        return ScopeDecision(DecideResult.GRANTED, names)

    async def _grant(
        self, uow: IdentityUnitOfWorkPort, offer: ScopeOffer, via: str
    ) -> tuple[str, ...]:
        release = _release(offer.release_id)
        user = await uow.users.get(offer.user_id)
        if (
            release is None
            or release.server not in OFFERABLE_SERVERS
            or user is None
            or user.status != UserStatus.ACTIVE
            or not role_may_use_server(user.roles, release.server)
        ):
            return ()
        allowed = set(SCOPE_NAMES_BY_SERVER[release.server]) & set(release.scopes)
        scopes = [scope for scope in offer.scopes if scope in allowed]
        # Locked: a revocation at the same moment cannot be overwritten by the save.
        connectors = await uow.connectors.lock_for_user(
            offer.connector_ids, offer.user_id
        )
        now = self.clock.now()
        widened = [
            c for c in connectors if c.server == release.server and c.is_active(now)
        ]
        for connector in widened:
            await _widen(uow, connector, scopes, offer.release_id, via)
        self._clear_cache_after_commit(uow, [c.id for c in widened])
        return tuple(c.name for c in widened)

    def _clear_cache_after_commit(
        self, uow: IdentityUnitOfWorkPort, connector_ids: list[UUID]
    ) -> None:
        async def clear() -> None:
            try:
                await self.overlay_cache.invalidate(connector_ids)
            except Exception:  # noqa: BLE001 - the entries end within 30 seconds anyway
                log.warning("mcp.scope_overlay_invalidate_failed")

        uow.after_commit(clear)


async def _widen(
    uow: IdentityUnitOfWorkPort,
    connector: McpConnector,
    scopes: list[str],
    release_id: str,
    via: str,
) -> None:
    """Tokens hold their scopes in `scopes`; an OAuth token's `scp` cannot change."""
    field = connector.scopes if connector.kind == "token" else connector.extra_scopes
    added = [scope for scope in scopes if scope not in field]
    field.extend(added)
    await uow.connectors.save(connector)
    uow.audit(
        make_audit(
            CONNECTOR_SCOPES_EXTENDED,
            user_id=connector.user_id,
            connector_id=str(connector.id),
            server=connector.server,
            release_id=release_id,
            scopes=added,
            via=via,
        )
    )

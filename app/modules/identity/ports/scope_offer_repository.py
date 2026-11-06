"""Ports: persistence of scope offers and the cache of the OAuth overlay."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.scope_offer import ScopeOffer


class ScopeOfferRepository(Protocol):
    """Reads and writes id.mcp_scope_offers."""

    async def add_if_new(self, offer: ScopeOffer) -> bool:
        """Insert unless the user has an offer of this release; False when not new."""
        ...

    async def get_by_token_hash(self, token_hash: str) -> ScopeOffer | None:
        """Find an offer by the hash of its token."""
        ...

    async def get(self, offer_id: UUID) -> ScopeOffer | None:
        """Find an offer by id."""
        ...

    async def list_open_for_user(
        self, user_id: UUID, now: datetime
    ) -> list[ScopeOffer]:
        """The user's pending, unexpired offers, soonest to expire first."""
        ...

    async def decide(
        self, offer_id: UUID, status: str, now: datetime
    ) -> ScopeOffer | None:
        """Atomically decide a pending, unexpired offer; None when it is not one."""
        ...

    async def expire_overdue(self, now: datetime) -> int:
        """Mark the pending offers past their expiry; return how many."""
        ...

    async def users_to_offer(
        self,
        release_id: str,
        server: str,
        scopes: Sequence[str],
        now: datetime,
        *,
        after: UUID | None,
        limit: int,
    ) -> list[UUID]:
        """Users with an active connector missing a scope and no offer, by id."""
        ...


class ScopeOverlayCache(Protocol):
    """The short cache of connectors' extra scopes."""

    async def invalidate(self, connector_ids: Sequence[UUID]) -> None:
        """Forget the cached extra scopes of these connectors."""
        ...

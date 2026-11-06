"""SQLAlchemy repository of scope offers (id.mcp_scope_offers)."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.identity.domain.scope_offer import (
    OFFER_STATUS_EXPIRED,
    OFFER_STATUS_PENDING,
    ScopeOffer,
)
from app.modules.identity.infrastructure.orm import McpConnector, McpScopeOffer

from sqlalchemy import ARRAY, Text, cast, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: McpScopeOffer) -> ScopeOffer:
    return ScopeOffer(
        id=row.id,
        user_id=row.user_id,
        release_id=row.release_id,
        scopes=list(row.scopes),
        connector_ids=list(row.connector_ids),
        status=row.status,
        token_hash=row.token_hash,
        expires_at=row.expires_at,
        decided_at=row.decided_at,
        created_at=row.created_at,
    )


class SqlScopeOfferRepository:
    """ScopeOfferRepository over an open AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self._session = session

    async def add_if_new(self, offer: ScopeOffer) -> bool:
        """Insert unless the user has an offer of this release; False when not new."""
        inserted = await self._session.scalar(
            insert(McpScopeOffer)
            .values(
                id=offer.id,
                user_id=offer.user_id,
                release_id=offer.release_id,
                scopes=offer.scopes,
                connector_ids=offer.connector_ids,
                status=offer.status,
                token_hash=offer.token_hash,
                expires_at=offer.expires_at,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "release_id"])
            .returning(McpScopeOffer.id)
        )
        return inserted is not None

    async def get_by_token_hash(self, token_hash: str) -> ScopeOffer | None:
        """Find an offer by the hash of its token."""
        row = await self._session.scalar(
            select(McpScopeOffer).where(McpScopeOffer.token_hash == token_hash)
        )
        return _to_entity(row) if row else None

    async def get(self, offer_id: UUID) -> ScopeOffer | None:
        """Find an offer by id."""
        row = await self._session.get(McpScopeOffer, offer_id)
        return _to_entity(row) if row else None

    async def list_open_for_user(
        self, user_id: UUID, now: datetime
    ) -> list[ScopeOffer]:
        """The user's pending, unexpired offers, soonest to expire first."""
        rows = await self._session.scalars(
            select(McpScopeOffer)
            .where(
                McpScopeOffer.user_id == user_id,
                McpScopeOffer.status == OFFER_STATUS_PENDING,
                McpScopeOffer.expires_at > now,
            )
            .order_by(McpScopeOffer.expires_at)
        )
        return [_to_entity(row) for row in rows]

    async def decide(
        self, offer_id: UUID, status: str, now: datetime
    ) -> ScopeOffer | None:
        """Atomically decide a pending, unexpired offer; None when it is not one."""
        row = await self._session.scalar(
            update(McpScopeOffer)
            .where(
                McpScopeOffer.id == offer_id,
                McpScopeOffer.status == OFFER_STATUS_PENDING,
                McpScopeOffer.expires_at > now,
            )
            .values(status=status, decided_at=now)
            .returning(McpScopeOffer)
            .execution_options(populate_existing=True)
        )
        return _to_entity(row) if row else None

    async def expire_overdue(self, now: datetime) -> int:
        """Mark the pending offers past their expiry; return how many."""
        result = await self._session.execute(
            update(McpScopeOffer)
            .where(
                McpScopeOffer.status == OFFER_STATUS_PENDING,
                McpScopeOffer.expires_at <= now,
            )
            .values(status=OFFER_STATUS_EXPIRED)
            .returning(McpScopeOffer.id)
        )
        return len(result.all())

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
        offered = select(McpScopeOffer.user_id).where(
            McpScopeOffer.release_id == release_id
        )
        held = McpConnector.scopes + McpConnector.extra_scopes
        stmt = (
            select(McpConnector.user_id)
            .where(
                McpConnector.server == server,
                McpConnector.revoked_at.is_(None),
                or_(McpConnector.expires_at.is_(None), McpConnector.expires_at > now),
                ~held.op("@>")(cast(list(scopes), ARRAY(Text))),
                McpConnector.user_id.not_in(offered),
            )
            .distinct()
            .order_by(McpConnector.user_id)
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(McpConnector.user_id > after)
        return list((await self._session.scalars(stmt)).all())

"""What the broadcast use cases return: the broadcast, its author and its stats."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.admin.domain.broadcast import (
    Broadcast,
    BroadcastStats,
    BroadcastStatus,
)
from app.modules.admin.ports.unit_of_work import AdminUnitOfWork
from app.shared.contracts.identity import IdentityDirectory, UserRef


@dataclass(frozen=True, slots=True)
class BroadcastView:
    """A broadcast with its author and live delivery stats."""

    broadcast: Broadcast
    author: UserRef | None
    stats: BroadcastStats | None


@dataclass(frozen=True, slots=True)
class BroadcastPageView:
    """A page of broadcasts and the cursor of the next page."""

    items: list[BroadcastView]
    next_cursor: str | None


class BroadcastPresenter:
    """Adds author names and delivery stats to broadcasts."""

    def __init__(self, identity: IdentityDirectory) -> None:
        """Store the identity directory used for author names."""
        self.identity = identity

    async def present(
        self, uow: AdminUnitOfWork, broadcasts: Sequence[Broadcast]
    ) -> list[BroadcastView]:
        """Build views; stats are live while sending and frozen once sent."""
        author_ids = sorted({b.author_id for b in broadcasts}, key=str)
        authors = await self.identity.get_users(author_ids) if author_ids else {}
        return [
            BroadcastView(b, authors.get(b.author_id), await self._stats(uow, b))
            for b in broadcasts
        ]

    @staticmethod
    async def _stats(
        uow: AdminUnitOfWork, broadcast: Broadcast
    ) -> BroadcastStats | None:
        if broadcast.status != BroadcastStatus.SENDING:
            return broadcast.stats
        counts = await uow.deliveries.counts(broadcast.id)
        expected = broadcast.stats.total if broadcast.stats else counts.total
        return BroadcastStats(
            total=max(expected, counts.total),
            sent=counts.sent,
            failed=counts.failed,
            blocked=counts.blocked,
        )

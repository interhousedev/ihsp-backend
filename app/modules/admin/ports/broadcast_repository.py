"""Storage port for broadcasts."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.admin.domain.broadcast import Broadcast, BroadcastStatus


class BroadcastRepository(Protocol):
    """Reads and writes broadcasts."""

    async def add(self, broadcast: Broadcast) -> None:
        """Insert a new broadcast."""
        ...

    async def get(self, broadcast_id: UUID, *, for_update: bool = False) -> Broadcast:
        """Return the broadcast or raise BroadcastNotFoundError; lock it if asked."""
        ...

    async def save(self, broadcast: Broadcast) -> None:
        """Store title, text, media, audience, schedule, status and stats."""
        ...

    async def list_page(
        self,
        *,
        status: BroadcastStatus | None,
        before: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Broadcast]:
        """Return broadcasts newest first after the keyset cursor."""
        ...

    async def claim_scheduled(self, now: datetime) -> list[Broadcast]:
        """Lock scheduled broadcasts whose time has come (SKIP LOCKED)."""
        ...

    async def list_sending(self) -> list[Broadcast]:
        """Return broadcasts that are being delivered."""
        ...

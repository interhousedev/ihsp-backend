"""Storage port for Web Push subscriptions."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.notify.domain.push_subscription import PushSubscription


class PushSubscriptionRepository(Protocol):
    """Subscriptions of the users' devices."""

    async def upsert(
        self,
        *,
        user_id: UUID,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None,
        now: datetime,
    ) -> UUID:
        """Insert by endpoint or move an existing one to the user; return the id."""
        ...

    async def trim(self, user_id: UUID, keep: int) -> int:
        """Delete the user's oldest subscriptions beyond `keep`; return how many."""
        ...

    async def delete_by_endpoint(self, user_id: UUID, endpoint: str) -> bool:
        """Delete the user's subscription with this endpoint; False when none."""
        ...

    async def list_for_user(self, user_id: UUID) -> list[PushSubscription]:
        """Return the user's subscriptions, oldest first."""
        ...

    async def delete_many(self, ids: Sequence[UUID]) -> None:
        """Delete subscriptions by id."""
        ...

    async def record_success(self, ids: Sequence[UUID], now: datetime) -> None:
        """Set `last_success_at` and reset the failure counter."""
        ...

    async def record_failure(self, subscription_id: UUID) -> int:
        """Add one failure and return the new count."""
        ...

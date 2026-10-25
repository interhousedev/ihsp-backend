"""A PushSender that records what it sends and can fail on demand."""

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.notify.domain.push_subscription import PushSubscription


@dataclass(frozen=True, slots=True)
class PushItem:
    """One call to the sender."""

    subscription_id: UUID
    endpoint: str
    payload: dict[str, Any]
    raw: str


class FakePushSender:
    """Implements PushSender; `fail_next(subscription_id, error)` raises once."""

    def __init__(self) -> None:
        """Start with an empty record."""
        self.items: list[PushItem] = []
        self._failures: dict[UUID, deque[Exception]] = defaultdict(deque)

    def fail_next(self, subscription_id: UUID, error: Exception) -> None:
        """Make the next send to this subscription raise the error (once)."""
        self._failures[subscription_id].append(error)

    def to(self, subscription_id: UUID) -> list[PushItem]:
        """Return the messages sent to one subscription."""
        return [i for i in self.items if i.subscription_id == subscription_id]

    async def send(self, subscription: PushSubscription, payload: str) -> None:
        """Record a message."""
        queue = self._failures.get(subscription.id)
        if queue:
            raise queue.popleft()
        self.items.append(
            PushItem(
                subscription_id=subscription.id,
                endpoint=subscription.endpoint,
                payload=json.loads(payload),
                raw=payload,
            )
        )

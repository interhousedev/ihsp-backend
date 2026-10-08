"""Port that counts the delivery of a broadcast from its notifications."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DeliveryCounts:
    """Notifications of one broadcast by delivery outcome."""

    total: int
    sent: int
    failed: int
    blocked: int
    open: int
    """Still pending, sending or waiting for a retry."""


class DeliveryReader(Protocol):
    """Reads delivery counts (the single source of truth is the notifications)."""

    async def counts(self, broadcast_id: UUID) -> DeliveryCounts:
        """Count the broadcast's notifications."""
        ...

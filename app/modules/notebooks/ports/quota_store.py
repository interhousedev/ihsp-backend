"""Port: per-kind daily output counters and the set of running outputs."""

from datetime import date
from typing import Protocol
from uuid import UUID


class QuotaStore(Protocol):
    """Counters in Redis (`nb:quota:{user}:{day}:{kind}`, `nb:running:{user}`)."""

    async def used(self, user_id: UUID, day: date, kind: str) -> int:
        """How many outputs of the kind (or `"artifacts"` for all) were counted."""
        ...

    async def add(self, user_id: UUID, day: date, kind: str) -> int:
        """Count one output; return the new value (kept 48 hours)."""
        ...

    async def remove(self, user_id: UUID, day: date, kind: str) -> None:
        """Undo one count (a failed provider call is not counted); never below 0."""
        ...

    async def running(self, user_id: UUID) -> set[UUID]:
        """Ids of the user's outputs that are queued or generating."""
        ...

    async def add_running(self, user_id: UUID, artifact_id: UUID) -> None:
        """Mark an output as running."""
        ...

    async def remove_running(self, user_id: UUID, artifact_id: UUID) -> None:
        """Mark an output as finished."""
        ...

    async def clear(self, user_id: UUID) -> None:
        """Forget the user's running outputs (the account is deleted)."""
        ...

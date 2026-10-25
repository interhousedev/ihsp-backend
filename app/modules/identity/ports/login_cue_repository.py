"""Port: storage of login cues (id.login_cues)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.login_cue import LoginCue


class LoginCueRepository(Protocol):
    """Persistence of login cues."""

    async def add(self, cues: Sequence[LoginCue]) -> None:
        """Insert the cues in one transaction."""
        ...

    async def get(self, cue_id: UUID) -> LoginCue | None:
        """Return the cue with this id, consumed or not."""
        ...

    async def list_cues(self, group_id: UUID | None = None) -> list[LoginCue]:
        """Return all cues, optionally of one group, newest first."""
        ...

    async def delete(self, cue_id: UUID) -> bool:
        """Delete the cue; False when it did not exist."""
        ...

    async def open_group_ids(self) -> list[UUID]:
        """Return the groups that still have unconsumed cues."""
        ...

    async def open_for_group(self, group_id: UUID) -> list[LoginCue]:
        """Return the unconsumed cues of one group."""
        ...

    async def reserve(
        self, cue_id: UUID, now: datetime, until: datetime
    ) -> LoginCue | None:
        """Hold an unconsumed, unheld cue until ``until``; None when it cannot be held.

        One conditional UPDATE: of two concurrent callers only one gets the cue.
        """
        ...

    async def release(self, cue_id: UUID) -> None:
        """Drop the hold of a cue (a failed registration)."""
        ...

    async def claim(self, cue_id: UUID, now: datetime) -> bool:
        """Mark an unconsumed cue consumed and drop its hold; False when consumed."""
        ...

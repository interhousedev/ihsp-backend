"""Ports of the level schemes: storage, per-learner high-water marks, XP totals."""

from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.engagement.levels import LevelScheme


class LevelSchemeRepository(Protocol):
    """Stores level schemes; one active scheme per platform and per course."""

    async def add(self, scheme: LevelScheme) -> None:
        """Store a new scheme."""
        ...

    async def get(self, id: UUID) -> LevelScheme | None:
        """Return a scheme."""
        ...

    async def update(self, scheme: LevelScheme) -> None:
        """Replace a stored scheme."""
        ...

    async def list(self) -> list[LevelScheme]:
        """Return every scheme, newest first."""
        ...

    async def active_platform(self) -> LevelScheme:
        """Return the active platform scheme or the default one."""
        ...

    async def for_course(self, course_id: UUID) -> LevelScheme | None:
        """Return the active scheme of a course."""
        ...

    async def deactivate_platform(self) -> None:
        """Deactivate the platform schemes."""
        ...

    async def activate(self, id: UUID) -> None:
        """Activate a scheme (a course scheme replaces the course's active one)."""
        ...


class ProfileLevels(Protocol):
    """Highest level ever shown to a learner, on the platform and per course."""

    async def highest_level(self, user_id: UUID, course_id: UUID | None) -> int:
        """Return the mark (1 when none)."""
        ...

    async def set_highest(
        self, user_id: UUID, course_id: UUID | None, level: int
    ) -> None:
        """Raise the mark."""
        ...


class XpTotals(Protocol):
    """Total XP of every learner."""

    async def all_totals(self) -> list[int]:
        """Return one total per learner."""
        ...

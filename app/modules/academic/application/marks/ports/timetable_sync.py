"""Port: refresh a group's EMIS timetable (implemented by the schedule)."""

from collections.abc import Collection, Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.schedule.material_scope import MaterialScope


class TimetableOutcome(Protocol):
    """How a timetable sync ended."""

    @property
    def status(self) -> str:
        """One of the sync's statuses, e.g. synced or emis_unavailable."""
        ...


class TimetableSync(Protocol):
    """Reads a group's classes through one student's EMIS link and applies them."""

    async def execute(
        self, *, group_id: UUID, user_id: UUID, refresh_bells: bool = True
    ) -> TimetableOutcome:
        """Apply the timetable; EMIS errors come back as a status, not an exception."""
        ...


class MaterialResync(Protocol):
    """Replaces a group's EMIS materials in some terms (implemented by the schedule)."""

    async def resync_materials(
        self,
        *,
        group_id: UUID,
        terms: Collection[tuple[str, int]] | None,
        fetchers: Sequence[Sequence[UUID]],
        scope: MaterialScope | None = None,
    ) -> int:
        """Purge and re-import (terms None: the current one); return how many."""
        ...

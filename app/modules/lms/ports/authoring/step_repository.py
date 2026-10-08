"""Port: storage of course steps (identity and working copy)."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.authoring.entities import CourseStep


class StepRepository(Protocol):
    """Reads and writes course steps."""

    async def get(self, step_id: UUID) -> CourseStep | None:
        """Return the step, or None."""
        ...

    async def get_locked(self, step_id: UUID) -> CourseStep | None:
        """Return the step and lock its row until the transaction ends."""
        ...

    async def get_many(self, step_ids: Sequence[UUID]) -> dict[UUID, CourseStep]:
        """Return the steps that exist, by ID."""
        ...

    async def list_for_course(self, course_id: UUID) -> list[CourseStep]:
        """Return every step of the course."""
        ...

    async def add(self, step: CourseStep) -> None:
        """Insert a step."""
        ...

    async def save_draft(self, step: CourseStep) -> None:
        """Write the draft, its hash, files, lock version and author fields."""
        ...

    async def set_live(
        self, step_id: UUID, *, revision_id: UUID, live_hash: str
    ) -> None:
        """Point the step at the revision of the live version."""
        ...

    async def clear_live(self, step_ids: Sequence[UUID]) -> None:
        """Clear the live pointers of steps that left the live version."""
        ...

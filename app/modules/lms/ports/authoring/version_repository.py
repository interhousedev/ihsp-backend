"""Port: storage of course versions."""

from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.authoring.entities import CourseVersion


class VersionRepository(Protocol):
    """Reads and appends course versions."""

    async def add(self, version: CourseVersion) -> None:
        """Insert a version."""
        ...

    async def next_number(self, course_id: UUID) -> int:
        """Return the number the next version gets (call under the course lock)."""
        ...

    async def get(self, version_id: UUID) -> CourseVersion | None:
        """Return a version by ID, or None."""
        ...

    async def get_by_number(self, course_id: UUID, number: int) -> CourseVersion | None:
        """Return a version by its number, or None."""
        ...

    async def list_for_course(self, course_id: UUID) -> list[CourseVersion]:
        """Return the versions, newest first."""
        ...

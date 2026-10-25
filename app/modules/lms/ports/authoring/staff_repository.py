"""Port: storage of course staff."""

from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.authoring.entities import StaffMember


class StaffRepository(Protocol):
    """Reads and writes the staff of courses."""

    async def list_for_course(self, course_id: UUID) -> list[StaffMember]:
        """Return the staff ordered by position."""
        ...

    async def get(self, course_id: UUID, user_id: UUID) -> StaffMember | None:
        """Return one staff member, or None."""
        ...

    async def add(self, member: StaffMember) -> None:
        """Insert a staff member."""
        ...

    async def save(self, member: StaffMember) -> None:
        """Write role, permissions, visibility and position."""
        ...

    async def remove(self, course_id: UUID, user_id: UUID) -> None:
        """Delete a staff member."""
        ...

    async def count_with_permission(self, course_id: UUID, permission: str) -> int:
        """Count staff members holding the permission."""
        ...

"""Port: course staff."""

from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.learning.entities import StaffMember


class StaffRepository(Protocol):
    """Course staff members."""

    async def get(self, course_id: UUID, user_id: UUID) -> StaffMember | None:
        """Return the staff row of a user in a course."""
        ...

    async def list_on_page(self, course_id: UUID) -> list[StaffMember]:
        """Return staff shown on the course page, ordered by position."""
        ...

    async def course_ids_of(self, user_id: UUID) -> list[UUID]:
        """Return the courses where the user is on the staff."""
        ...

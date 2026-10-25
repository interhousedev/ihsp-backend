"""Port: enrollments."""

from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.learning.entities import Enrollment


class EnrollmentRepository(Protocol):
    """A user's enrollments in courses."""

    async def get(self, course_id: UUID, user_id: UUID) -> Enrollment | None:
        """Return the enrollment of a user in a course."""
        ...

    async def add(self, *, course_id: UUID, user_id: UUID, via: str) -> Enrollment:
        """Enroll the user; if they are enrolled already, return the existing row."""
        ...

    async def save(self, enrollment: Enrollment) -> None:
        """Store progress, completion and the last seen version."""
        ...

    async def list_for_user(self, user_id: UUID) -> list[Enrollment]:
        """Return all enrollments of a user."""
        ...

    async def list_for_course(self, course_id: UUID) -> list[Enrollment]:
        """Return all enrollments in a course."""
        ...

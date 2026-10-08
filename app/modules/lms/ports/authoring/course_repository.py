"""Port: storage of courses."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.authoring.entities import Course


class CourseRepository(Protocol):
    """Reads and writes courses and their draft working copy."""

    async def get(self, course_id: UUID) -> Course | None:
        """Return the course, or None."""
        ...

    async def get_locked(self, course_id: UUID) -> Course | None:
        """Return the course and lock its row until the transaction ends."""
        ...

    async def add(self, course: Course) -> None:
        """Insert a course; raise SlugTakenError if the slug is used."""
        ...

    async def save(self, course: Course) -> None:
        """Write every mutable field (call only while holding the row lock)."""
        ...

    async def slug_exists(self, slug: str) -> bool:
        """Return True if a course already uses the slug."""
        ...

    async def touch_draft(self, course_id: UUID, *, by: UUID, now: datetime) -> int:
        """Atomically bump `draft_seq`, which also takes the row lock; return it."""
        ...

    async def list_all(self) -> list[Course]:
        """Return every course, newest first (for LMS admins)."""
        ...

    async def list_for_user(self, user_id: UUID, permission: str) -> list[Course]:
        """Return courses where the user holds the permission."""
        ...

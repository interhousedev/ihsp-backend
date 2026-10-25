"""Port: read access to courses for students and staff."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.learning.entities import LearningCourse


class CourseRepository(Protocol):
    """Courses with their live values."""

    async def get(self, course_id: UUID) -> LearningCourse | None:
        """Return the course by id."""
        ...

    async def get_by_slug(self, slug: str) -> LearningCourse | None:
        """Return the course by its unique slug."""
        ...

    async def get_by_invite_code(self, code: str) -> LearningCourse | None:
        """Return the course that currently uses the invite code."""
        ...

    async def get_many(self, course_ids: Sequence[UUID]) -> list[LearningCourse]:
        """Return the courses with these ids, ordered by title."""
        ...

    async def search_published(
        self, query: str | None, *, limit: int
    ) -> list[LearningCourse]:
        """Return published, active, public courses whose title contains the query."""
        ...

    async def list_all(self, *, limit: int) -> list[LearningCourse]:
        """Return every course, ordered by title (for LMS administrators)."""
        ...

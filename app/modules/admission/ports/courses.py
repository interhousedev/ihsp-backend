"""Port: live course sources (academic marks and LMS enrolments)."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.courses import Course
from app.shared.actor import Actor
from app.shared.contracts.admission_assistant import CourseHit


class CourseSources(Protocol):
    """Reads the courses other modules know for a student."""

    async def academic_courses(self, student_id: UUID) -> list[Course]:
        """Return the student's lyceum subjects of the current semester."""
        ...

    async def lms_courses(self, actor: Actor) -> list[Course]:
        """Return the LMS courses the actor is enrolled in."""
        ...

    async def lms_catalog(self, actor: Actor, query: str | None) -> list[Course]:
        """Return public LMS courses the actor may open, filtered by title."""
        ...

    async def lms_find(
        self, actor: Actor, query: str | None, limit: int
    ) -> list[CourseHit]:
        """Return open LMS courses the actor may see, enrolments marked."""
        ...

    async def lms_enroll(self, actor: Actor, course_id: UUID) -> None:
        """Enroll the actor in a public LMS course."""
        ...

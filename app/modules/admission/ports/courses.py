"""Port: live course sources (academic marks and LMS enrolments)."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.courses import Course
from app.shared.actor import Actor


class CourseSources(Protocol):
    """Reads the courses other modules know for a student."""

    async def academic_courses(self, student_id: UUID) -> list[Course]:
        """Return the student's lyceum subjects of the current semester."""
        ...

    async def lms_courses(self, actor: Actor) -> list[Course]:
        """Return the LMS courses the actor is enrolled in."""
        ...

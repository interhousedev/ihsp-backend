"""Club <-> LMS course link (provider: lms; consumer: activities).

The LMS module implements `CourseDirectory` over its course tables and hands it to
the activities wiring; activities never reads LMS tables. A course counts as
staffed by the owner and every teacher currently assigned to it.
"""

from typing import Protocol
from uuid import UUID


class CourseDirectory(Protocol):
    """Course lookup needed to link a club to a course."""

    async def exists(self, course_id: UUID) -> bool:
        """Whether the course exists."""
        ...

    async def is_staff(self, course_id: UUID, user_id: UUID) -> bool:
        """Whether the person owns or teaches the course right now."""
        ...

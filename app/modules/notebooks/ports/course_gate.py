"""Port: who may open the workspace notebook of an LMS course (§ 3.1 of LMS-AI)."""

from typing import Protocol
from uuid import UUID

from app.shared.contracts.lms import CourseWorkspaceAccess


class CourseGate(Protocol):
    """The course permissions of a user, as the workspace access check needs them."""

    async def access(
        self, user_id: UUID, course_id: UUID
    ) -> CourseWorkspaceAccess | None:
        """Return what the user may do in the course; None for a stranger.

        Course staff and LMS admins count; students and unknown courses are None.
        """
        ...

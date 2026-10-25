"""Use case: recent test attempts of a course, for reviewers (LMS-20)."""

from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.domain.authoring.permissions import REVIEW
from app.shared.actor import Actor

MAX_ATTEMPTS = 200


class ListCourseAttempts:
    """Read the latest attempts straight from the attempts table."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self, actor: Actor, course_id: UUID, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return up to `limit` attempts, newest first (needs `review`)."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(REVIEW)
            return await uow.attempts.recent_for_course(
                course_id, max(1, min(limit, MAX_ATTEMPTS))
            )

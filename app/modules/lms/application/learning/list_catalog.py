"""Use case: the catalog of published public courses (UF-LMS-01)."""

from typing import Final
from uuid import UUID

from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.course_page import course_card
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import LearningCourseCardView
from app.modules.lms.domain.access_rules import AccessState
from app.shared.actor import Actor

CATALOG_LIMIT: Final = 200


class ListCatalog:
    """List the courses anyone can enroll in."""

    def __init__(self, uow_factory: UowFactory, gate: AudienceGate) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.gate = gate

    async def execute(
        self, *, query: str | None = None, actor: Actor | None = None
    ) -> list[LearningCourseCardView]:
        """Return published, active, public courses, optionally filtered by title.

        With an ``actor``, the cards of the courses the actor is enrolled in carry
        their stored progress; other cards keep ``progress_pct`` None. The
        enrolments are read in one query, so the catalog costs no per-course query.
        """
        async with self.uow_factory() as uow:
            courses = await uow.courses.search_published(
                (query or "").strip() or None, limit=CATALOG_LIMIT
            )
            access = await self.gate.courses(uow, actor, [c.id for c in courses])
            courses = [
                c for c in courses if access[c.id].state is not AccessState.HIDDEN
            ]
            versions = await uow.versions.get_many(
                [c.live_version_id for c in courses if c.live_version_id is not None]
            )
            progress: dict[UUID, int] = {}
            if actor is not None:
                progress = {
                    e.course_id: e.progress_pct
                    for e in await uow.enrollments.list_for_user(actor.user_id)
                }
        return [
            course_card(
                course,
                (
                    versions.get(course.live_version_id)
                    if course.live_version_id
                    else None
                ),
                progress_pct=progress.get(course.id),
                access=access[course.id],
            )
            for course in courses
        ]

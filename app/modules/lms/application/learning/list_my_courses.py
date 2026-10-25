"""Use case: my courses, enrolled and managed (UF-LMS-01, step 4)."""

from collections.abc import Iterable
from typing import Final
from uuid import UUID

from app.modules.lms.application.learning.course_page import course_card
from app.modules.lms.application.learning.progress_service import ensure_progress
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import (
    LearningCourseCardView,
    LearningMyCoursesView,
)
from app.modules.lms.domain.learning.entities import LearningCourse, LiveVersion
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.actor import Actor, Role
from app.shared.clock import Clock

MANAGED_LIMIT: Final = 500


class ListMyCourses:
    """List the courses a user studies and the courses they manage."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, actor: Actor) -> LearningMyCoursesView:
        """Return enrolled courses (with fresh progress) and managed courses."""
        async with self.uow_factory() as uow:
            enrolled = await self._enrolled(uow, actor)
            managed = await self._managed(uow, actor)
            await uow.commit()
        return LearningMyCoursesView(enrolled=enrolled, managed=managed)

    async def _enrolled(
        self, uow: LearningUnitOfWork, actor: Actor
    ) -> list[LearningCourseCardView]:
        """Return the cards of enrolled courses; progress is refreshed lazily."""
        enrollments = await uow.enrollments.list_for_user(actor.user_id)
        courses = {
            c.id: c
            for c in await uow.courses.get_many([e.course_id for e in enrollments])
        }
        versions = await _versions_of(uow, courses.values())
        cards: list[LearningCourseCardView] = []
        for enrollment in enrollments:
            course = courses.get(enrollment.course_id)
            version = (
                versions.get(course.live_version_id)
                if course and course.live_version_id
                else None
            )
            if course is None or version is None:
                continue
            await ensure_progress(uow, enrollment, version, self.clock.now())
            cards.append(
                course_card(course, version, progress_pct=enrollment.progress_pct)
            )
        return sorted(cards, key=lambda card: card.title.casefold())

    async def _managed(
        self, uow: LearningUnitOfWork, actor: Actor
    ) -> list[LearningCourseCardView]:
        """Return courses where the user is staff; LMS admins manage all courses."""
        if actor.has(Role.LMS_ADMIN):
            courses = await uow.courses.list_all(limit=MANAGED_LIMIT)
        else:
            ids = await uow.staff.course_ids_of(actor.user_id)
            courses = await uow.courses.get_many(ids)
        versions = await _versions_of(uow, courses)
        return [
            course_card(
                course,
                (
                    versions.get(course.live_version_id)
                    if course.live_version_id
                    else None
                ),
                progress_pct=None,
            )
            for course in courses
        ]


async def _versions_of(
    uow: LearningUnitOfWork, courses: Iterable[LearningCourse]
) -> dict[UUID, LiveVersion]:
    """Load the live versions of the courses in one query."""
    ids = [c.live_version_id for c in courses if c.live_version_id is not None]
    return await uow.versions.get_many(ids)

"""Course steps as notebook sources (implements ``LmsSourceReader``)."""

from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.revision_loading import load_revision
from app.modules.lms.application.learning.step_context import load_live_step
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.domain.learning.errors import (
    NotEnrolledError,
    StepNotFoundError,
)
from app.modules.lms.domain.learning.source_text import export_text
from app.shared.contracts.lms import LmsStepText


class LmsSourceReaderImpl:
    """Lists the courses of a student and reads their live steps as plain text.

    Reading is limited to the enrolled student: course staff get no special access
    here, and test blocks are never part of the text (LMS-17).
    """

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def my_courses(self, user_id: UUID) -> list[dict[str, Any]]:
        """Return the enrolled courses that have a live version, with their steps.

        Each item is ``{"id", "title", "steps": [{"id", "title", "section"}]}``,
        courses sorted by title, steps in outline order.
        """
        async with self.uow_factory() as uow:
            enrollments = await uow.enrollments.list_for_user(user_id)
            courses = await uow.courses.get_many(
                list(dict.fromkeys(e.course_id for e in enrollments))
            )
            versions = await uow.versions.get_many(
                [c.live_version_id for c in courses if c.live_version_id is not None]
            )
        items: list[dict[str, Any]] = []
        for course in sorted(courses, key=lambda c: c.title.casefold()):
            live_id = course.live_version_id
            version = versions.get(live_id) if live_id else None
            if version is None:
                continue
            items.append(
                {
                    "id": course.id,
                    "title": course.title,
                    "steps": [
                        {"id": step.step_id, "title": step.title, "section": s.title}
                        for s in version.manifest.sections
                        for step in s.steps
                    ],
                }
            )
        return items

    async def step_text(
        self, user_id: UUID, course_id: UUID, step_id: UUID
    ) -> LmsStepText:
        """Return the text of the live revision of a step.

        Raises:
            StepNotFoundError: The step is not in the live version of this course.
            NotEnrolledError: The user is not enrolled in the course.
        """
        async with self.uow_factory() as uow:
            context = await load_live_step(uow, step_id)
            if context.course.id != course_id:
                raise StepNotFoundError(params={"step_id": str(step_id)})
            if await uow.enrollments.get(course_id, user_id) is None:
                raise NotEnrolledError(params={"course_id": str(course_id)})
            revision = await load_revision(uow, context.live_step.revision_id)
        text, starts = export_text(revision.content)
        return LmsStepText(
            course_id=course_id,
            course_title=context.course.title,
            step_id=step_id,
            title=context.live_step.title,
            revision_id=str(context.live_step.revision_id),
            text=text,
            block_starts=starts,
        )

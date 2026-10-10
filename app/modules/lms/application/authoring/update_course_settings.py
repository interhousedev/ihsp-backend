"""Use case: change visibility, status or cover of a course (LMS-3)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import (
    access_to,
    load_course_locked,
)
from app.modules.lms.application.authoring.draft_writer import StepDraftWriter
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import CourseDraftView
from app.modules.lms.domain.authoring.course_rules import new_invite_code
from app.modules.lms.domain.authoring.enums import CourseStatus, Visibility
from app.modules.lms.domain.authoring.permissions import EDIT
from app.modules.lms.domain.authoring.unset import UNSET, Unset
from app.shared.actor import Actor
from app.shared.lms_scopes import COURSES_WRITE


class UpdateCourseSettings:
    """Update the settings that are not part of the draft working copy."""

    def __init__(
        self,
        uow_factory: UowFactory,
        presenter: Presenter,
        writer: StepDraftWriter,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.presenter = presenter
        self.writer = writer

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        *,
        visibility: Visibility | None = None,
        status: CourseStatus | None = None,
        cover_file_id: UUID | None | Unset = UNSET,
    ) -> CourseDraftView:
        """Apply the provided settings; `cover_file_id=None` removes the cover."""
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(EDIT)
            access.require_scope(COURSES_WRITE)
            if visibility is not None and visibility != course.visibility:
                course.visibility = visibility
                course.invite_code = (
                    new_invite_code() if visibility is Visibility.INVITE else None
                )
            if status is not None:
                course.status = status
            if not isinstance(cover_file_id, Unset):
                if cover_file_id is not None:
                    await self.writer.require_files([cover_file_id])
                course.cover_file_id = cover_file_id
            await uow.courses.save(course)
            await uow.commit()
            return await self.presenter.course_draft(uow, course, access)

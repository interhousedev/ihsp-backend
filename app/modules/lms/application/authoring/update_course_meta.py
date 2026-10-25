"""Use case: save the draft title and description (LMS-6, LMS-13)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import (
    access_to,
    load_course_locked,
)
from app.modules.lms.application.authoring.conflicts import course_conflict
from app.modules.lms.application.authoring.outline_editor import record_draft_change
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import CourseDraftView
from app.modules.lms.domain.authoring.course_rules import clean_title
from app.modules.lms.domain.authoring.permissions import EDIT
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.lms_scopes import COURSES_WRITE


class UpdateCourseMeta:
    """Overwrite the draft meta with optimistic locking."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, presenter: Presenter
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.presenter = presenter

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        *,
        title: str,
        description: str,
        lock_version: int,
    ) -> CourseDraftView:
        """Save the meta; a stale `lock_version` raises a conflict with `theirs`."""
        clean = clean_title(title)
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(EDIT)
            access.require_scope(COURSES_WRITE)
            if course.lock_version != lock_version:
                raise await course_conflict(self.presenter, uow, course, access)
            course.draft_meta = {"title": clean, "description": description}
            record_draft_change(
                course, outline=None, actor_id=actor.user_id, now=self.clock.now()
            )
            await uow.courses.save(course)
            await uow.commit()
            return await self.presenter.course_draft(uow, course, access)

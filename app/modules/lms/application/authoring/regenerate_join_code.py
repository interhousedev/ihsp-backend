"""Use case: replace the join code of a course."""

from uuid import UUID

from app.modules.lms.application.authoring.access import (
    access_to,
    load_course_locked,
)
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import InviteCodeView
from app.modules.lms.domain.authoring.course_rules import new_invite_code
from app.modules.lms.domain.authoring.permissions import EDIT
from app.shared.actor import Actor
from app.shared.lms_scopes import COURSES_WRITE


class RegenerateJoinCode:
    """Issue a new join code; the old one stops working."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, course_id: UUID) -> InviteCodeView:
        """Generate and store a new code, for any visibility."""
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(EDIT)
            access.require_scope(COURSES_WRITE)
            course.invite_code = new_invite_code()
            await uow.courses.save(course)
            await uow.commit()
            return InviteCodeView(invite_code=course.invite_code)

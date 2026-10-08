"""Use case: rotate the invite code of an invite-only course (LMS-3)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import (
    access_to,
    load_course_locked,
)
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import InviteCodeView
from app.modules.lms.domain.authoring.course_rules import new_invite_code
from app.modules.lms.domain.authoring.enums import Visibility
from app.modules.lms.domain.authoring.errors import InviteNotApplicableError
from app.modules.lms.domain.authoring.permissions import MANAGE_STAFF
from app.shared.actor import Actor


class RotateInviteCode:
    """Replace the invite code; old invite links stop working."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, course_id: UUID) -> InviteCodeView:
        """Generate and store a new invite code."""
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(MANAGE_STAFF)
            if course.visibility is not Visibility.INVITE:
                raise InviteNotApplicableError()
            course.invite_code = new_invite_code()
            await uow.courses.save(course)
            await uow.commit()
            return InviteCodeView(invite_code=course.invite_code)

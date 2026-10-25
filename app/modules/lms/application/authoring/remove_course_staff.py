"""Use case: remove a staff member from a course (LMS-5, UF-LMS-07)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.staff_guard import guard_last_manager
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.domain.authoring.errors import StaffMemberNotFoundError
from app.modules.lms.domain.authoring.permissions import MANAGE_STAFF
from app.shared.actor import Actor


class RemoveCourseStaff:
    """Remove a member; access of removed people ends at once."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, course_id: UUID, user_id: UUID) -> None:
        """Delete the member unless they are the last manager (admins may)."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(MANAGE_STAFF)
            member = await uow.staff.get(course_id, user_id)
            if member is None:
                raise StaffMemberNotFoundError(params={"user_id": str(user_id)})
            await guard_last_manager(uow, access, member, remaining=())
            await uow.staff.remove(course_id, user_id)
            await uow.commit()

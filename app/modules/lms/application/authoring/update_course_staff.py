"""Use case: change a staff member's role, permissions or visibility (LMS-5)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.staff_guard import guard_last_manager
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import CourseStaffItemView
from app.modules.lms.domain.authoring.errors import StaffMemberNotFoundError
from app.modules.lms.domain.authoring.permissions import (
    MANAGE_STAFF,
    normalize_permissions,
    normalize_role,
)
from app.shared.actor import Actor


class UpdateCourseStaff:
    """Apply a partial update to one staff member."""

    def __init__(self, uow_factory: UowFactory, presenter: Presenter) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.presenter = presenter

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        user_id: UUID,
        *,
        role: str | None = None,
        permissions: Sequence[str] | None = None,
        show_on_page: bool | None = None,
        position: int | None = None,
    ) -> CourseStaffItemView:
        """Update the provided fields; the last manager cannot lose `manage_staff`."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(MANAGE_STAFF)
            member = await uow.staff.get(course_id, user_id)
            if member is None:
                raise StaffMemberNotFoundError(params={"user_id": str(user_id)})
            if permissions is not None:
                granted = normalize_permissions(permissions)
                await guard_last_manager(uow, access, member, remaining=granted)
                member.permissions = granted
            if role is not None:
                member.role = normalize_role(role)
            if show_on_page is not None:
                member.show_on_page = show_on_page
            if position is not None:
                member.position = position
            await uow.staff.save(member)
            await uow.commit()
        return (await self.presenter.staff_items([member]))[0]

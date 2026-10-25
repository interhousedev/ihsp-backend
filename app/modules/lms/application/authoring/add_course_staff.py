"""Use case: add a user to the staff of a course (LMS-5, UF-LMS-06)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import CourseStaffItemView
from app.modules.lms.domain.authoring.entities import StaffMember
from app.modules.lms.domain.authoring.errors import (
    StaffAlreadyExistsError,
    UserNotFoundError,
)
from app.modules.lms.domain.authoring.permissions import (
    MANAGE_STAFF,
    normalize_permissions,
    normalize_role,
    preset_permissions,
)
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


class AddCourseStaff:
    """Add a user, found by login, with a role label and permissions."""

    def __init__(
        self,
        uow_factory: UowFactory,
        presenter: Presenter,
        identity: IdentityDirectory,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.presenter = presenter
        self.identity = identity

    async def execute(
        self,
        actor: Actor,
        course_id: UUID,
        *,
        login: str,
        role: str,
        permissions: Sequence[str] | None,
        show_on_page: bool = True,
        position: int = 0,
    ) -> CourseStaffItemView:
        """Add the member; without `permissions` a preset role name fills them."""
        label = normalize_role(role)
        granted = (
            normalize_permissions(permissions)
            if permissions is not None
            else (preset_permissions(label) or [])
        )
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(MANAGE_STAFF)
            user = await self.identity.user_by_login(login.strip())
            if user is None:
                raise UserNotFoundError(params={"login": login})
            if await uow.staff.get(course_id, user.id) is not None:
                raise StaffAlreadyExistsError(params={"user_id": str(user.id)})
            member = StaffMember(
                course_id=course_id,
                user_id=user.id,
                role=label,
                permissions=granted,
                show_on_page=show_on_page,
                position=position,
                added_by=actor.user_id,
            )
            await uow.staff.add(member)
            await uow.commit()
        return (await self.presenter.staff_items([member]))[0]

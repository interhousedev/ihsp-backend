"""The rule that a course keeps at least one manager (UF-LMS-07)."""

from collections.abc import Collection

from app.modules.lms.domain.authoring.entities import StaffMember
from app.modules.lms.domain.authoring.errors import LastManagerError
from app.modules.lms.domain.authoring.permissions import MANAGE_STAFF, CourseAccess
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork


async def guard_last_manager(
    uow: AuthoringUnitOfWork,
    access: CourseAccess,
    member: StaffMember,
    *,
    remaining: Collection[str],
) -> None:
    """Refuse a change that leaves the course without a `manage_staff` holder.

    Args:
        uow: Open unit of work.
        access: Access of the actor making the change; LMS admins may do it.
        member: The staff member being changed or removed.
        remaining: Permissions the member keeps (empty when removing).
    """
    if access.is_admin:
        return
    if MANAGE_STAFF not in member.permissions or MANAGE_STAFF in remaining:
        return
    if await uow.staff.count_with_permission(member.course_id, MANAGE_STAFF) <= 1:
        raise LastManagerError(params={"user_id": str(member.user_id)})

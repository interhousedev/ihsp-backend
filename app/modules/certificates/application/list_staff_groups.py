"""Groups (and subgroups) a staff member can filter by."""

from app.modules.certificates.application.staff_scope import StaffScope
from app.modules.certificates.ports.student_directory import GroupInfo
from app.shared.actor import Actor


class ListStaffGroups:
    """Administration sees every group, a curator only their own."""

    def __init__(self, *, scope: StaffScope) -> None:
        """Store the dependencies."""
        self._scope = scope

    async def execute(self, actor: Actor) -> list[GroupInfo]:
        """Return the groups the caller may see."""
        return await self._scope.groups(actor)

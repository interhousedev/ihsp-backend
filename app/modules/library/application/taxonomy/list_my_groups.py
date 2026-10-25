"""Groups the caller can aim a reading list at: taught or curated, or all."""

from app.modules.library.domain.access import is_librarian
from app.modules.library.ports.directories import AcademicDirectory, GroupView
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError


class ListMyGroups:
    """Teachers: groups they teach or curate; librarians and Administration: all."""

    def __init__(self, *, academic: AcademicDirectory) -> None:
        """Store the academic directory."""
        self.academic = academic

    async def execute(self, actor: Actor) -> list[GroupView]:
        """The groups for the reading-list scope `groups`."""
        if is_librarian(actor):
            return await self.academic.all_groups()
        if Role.TEACHER not in actor.roles:
            raise ForbiddenError(params={"roles": ["teacher", "librarian", "admin"]})
        return await self.academic.teacher_groups(actor.user_id)

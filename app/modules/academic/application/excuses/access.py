"""Who may see and decide an excuse (a stranger gets a 404, not a 403)."""

from uuid import UUID

from app.modules.academic.application.excuses.ports import ExcuseDirectory
from app.modules.academic.domain.excuses.errors import ExcuseNotFoundError
from app.modules.academic.domain.excuses.excuse import Excuse
from app.shared.actor import Actor, Role


class ExcuseAccess:
    """The student sees their own excuses; their curator and Administration see all."""

    def __init__(self, directory: ExcuseDirectory) -> None:
        """Store the directory."""
        self.directory = directory

    async def is_staff_of(self, student_id: UUID, actor: Actor) -> bool:
        """True for Administration and for the curator of the student's group."""
        if actor.has(Role.ADMIN):
            return True
        context = await self.directory.student_context(student_id)
        return context is not None and context.curator_id == actor.user_id

    def student_side(self, excuse: Excuse | None, actor: Actor) -> Excuse:
        """The excuse of this very student, else ``ExcuseNotFoundError``."""
        if excuse is None or excuse.student_id != actor.user_id:
            raise ExcuseNotFoundError()
        return excuse

    async def staff_side(self, excuse: Excuse | None, actor: Actor) -> Excuse:
        """An excuse of the curated student (or any, for Administration)."""
        if excuse is None or not await self.is_staff_of(excuse.student_id, actor):
            raise ExcuseNotFoundError()
        return excuse

    async def either_side(self, excuse: Excuse | None, actor: Actor) -> Excuse:
        """The student, their curator or Administration."""
        if excuse is not None and excuse.student_id == actor.user_id:
            return excuse
        return await self.staff_side(excuse, actor)

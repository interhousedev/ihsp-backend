"""A student's consecutive failed EMIS syncs (alerts of the Today page)."""

from uuid import UUID

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory


class GetSyncFailures:
    """Reads `students.sync_failures`, which a successful sync resets to zero."""

    def __init__(self, *, uow_factory: MarksUowFactory) -> None:
        """Store the unit of work factory."""
        self._uow_factory = uow_factory

    async def execute(self, user_id: UUID) -> int:
        """Return the number of failed syncs in a row (0 for a non-student)."""
        async with self._uow_factory() as uow:
            return await uow.students.sync_failures(user_id)

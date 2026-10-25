"""List and search subjects (ADM-7)."""

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.domain.schedule.subject import Subject


class ListSubjects:
    """Return subjects, optionally filtered by a name fragment."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory

    async def execute(self, query: str | None = None) -> list[Subject]:
        """Return subjects whose names or short name contain the query."""
        text = query.strip() if query else None
        async with self.uow_factory() as uow:
            return await uow.subjects.search(text or None)

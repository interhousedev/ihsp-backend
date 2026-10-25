"""Use case: the sources of a notebook in the order of the panel (NB-4)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class ListSources:
    """Reads all sources of the student's notebook."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, notebook_id: UUID) -> list[Source]:
        """Return the sources ordered by `position`.

        Raises:
            NotebookNotFoundError: The notebook is not the caller's.
        """
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, write=False)
            return await uow.sources.list_for_notebook(notebook_id)

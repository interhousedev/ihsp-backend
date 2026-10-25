"""Use case: tick or untick sources, one or all of them (NB-5)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class SelectSources:
    """Sets the `selected` checkbox that feeds the chat and Studio."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        selected: bool,
        ids: Sequence[UUID] | None = None,
    ) -> list[Source]:
        """Set the checkbox of `ids` (every source of the notebook when None).

        Ids of other notebooks are ignored. Returns all sources of the notebook.

        Raises:
            NotebookNotFoundError: The notebook is not the caller's.
        """
        async with self.uow_factory() as uow:
            notebook = await load_notebook(
                uow, actor.user_id, notebook_id, for_update=True
            )
            await uow.sources.set_selected(notebook_id, selected, ids)
            await sources_changed(uow, notebook, self.clock.now())
            await uow.commit()
            return await uow.sources.list_for_notebook(notebook_id)

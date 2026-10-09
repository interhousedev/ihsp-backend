"""Use case: remove a source and its passages (NB-4)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook, load_source
from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.errors import AutoNotebookReadOnlyError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class RemoveSource:
    """Deletes a source; chat messages and outputs keep their citation snapshots."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, actor: Actor, notebook_id: UUID, source_id: UUID) -> None:
        """Delete the source (its passages cascade) and refresh the notebook.

        Raises:
            NotebookNotFoundError: Notebook or source is not the caller's.
            AutoNotebookReadOnlyError: A lesson material of a subject or lesson
                notebook; exclude it instead (it would come back otherwise).
        """
        async with self.uow_factory() as uow:
            notebook = await load_notebook(
                uow, actor.user_id, notebook_id, for_update=True
            )
            source = await load_source(
                uow, actor.user_id, notebook_id, source_id, for_update=True
            )
            if notebook.is_auto and source.kind is SourceKind.LESSON_RESOURCE:
                raise AutoNotebookReadOnlyError()
            await uow.sources.delete(source_id)
            await sources_changed(uow, notebook, self.clock.now())
            await uow.commit()

"""Use case: delete a notebook (NB-3)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.errors import WorkspaceActionError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class DeleteNotebook:
    """Soft-deletes the student's notebook; `PurgeDeleted` removes it for good."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, actor: Actor, notebook_id: UUID) -> None:
        """Set `deleted_at`; a deleted or foreign notebook is a 404.

        Raises:
            NotebookNotFoundError: Not the caller's notebook.
            WorkspaceActionError: A course workspace cannot be deleted.
        """
        async with self.uow_factory() as uow:
            notebook = await load_notebook(
                uow, actor.user_id, notebook_id, for_update=True
            )
            if notebook.is_course_workspace:
                raise WorkspaceActionError(params={"action": "delete"})
            now = self.clock.now()
            notebook.deleted_at = now
            notebook.updated_at = now
            await uow.notebooks.save(notebook)
            await uow.commit()

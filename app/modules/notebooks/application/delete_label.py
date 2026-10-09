"""Use case: delete a label; the sources lose it (G12)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.label_access import load_label
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class DeleteLabel:
    """Removes a label of any origin and its links."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, notebook_id: UUID, label_id: UUID) -> None:
        """Delete the label; the next auto run may propose it again.

        Raises:
            NotebookNotFoundError: The notebook is not the caller's.
            WorkspaceReadOnlyError: A course member who may only read.
            LabelNotFoundError: No such label in the notebook.
        """
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, for_update=True)
            await load_label(uow, notebook_id, label_id)
            await uow.labels.delete([label_id])
            await uow.commit()

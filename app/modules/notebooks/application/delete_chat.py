"""Use case: delete the chat history of a notebook (NB-6, § 3.3.6)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.ports.turn_lock import TurnLock
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class DeleteChat:
    """Clears the student's thread in a notebook."""

    def __init__(self, uow_factory: UowFactory, turn_lock: TurnLock) -> None:
        """Store the unit of work factory and the per-thread lock."""
        self.uow_factory = uow_factory
        self.turn_lock = turn_lock

    async def execute(self, actor: Actor, notebook_id: UUID) -> None:
        """Delete every message of the student's thread.

        Raises:
            NotebookNotFoundError: Not the student's notebook.
            BusyError: A question is running in this thread.
        """
        async with self.turn_lock.hold(notebook_id, actor.user_id):
            async with self.uow_factory() as uow:
                await load_notebook(uow, actor.user_id, notebook_id, write=False)
                await uow.messages.delete_all(notebook_id, actor.user_id)
                await uow.commit()

"""Use case: read the chat of a notebook (NB-6, § 4.3)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.entities import NotebookMessage
from app.modules.notebooks.domain.limits import CHAT_LIST_LIMIT
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class GetChat:
    """Reads ``GET /notebooks/{id}/chat``."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, notebook_id: UUID) -> list[NotebookMessage]:
        """Return the last 200 messages of the student's own thread, oldest first."""
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, write=False)
            return await uow.messages.list_tail(
                notebook_id, actor.user_id, CHAT_LIST_LIMIT
            )

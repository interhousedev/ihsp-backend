"""Use case: rate an answer (NB-7, § 3.3.6)."""

from typing import Literal
from uuid import UUID

from app.modules.notebooks.application.answering import load_own_answer
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class MessageFeedback:
    """Stores the thumb of the student on one of the assistant's answers."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        message_id: UUID,
        rating: Literal["up", "down"],
        comment: str | None = None,
    ) -> None:
        """Set ``feedback`` to 1 (up) or -1 (down); a new rating replaces the old.

        The comment is accepted for the API but neither stored nor logged (it may
        quote the student's sources).

        Raises:
            NotebookNotFoundError: The notebook, or an assistant message of the
                student's own thread with that id, does not exist.
        """
        async with self.uow_factory() as uow:
            message = await load_own_answer(uow, actor.user_id, notebook_id, message_id)
            message.feedback = 1 if rating == "up" else -1
            await uow.messages.save(message)
            await uow.commit()

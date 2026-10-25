"""One of the caller's own feedback items with its responses."""

from uuid import UUID

from app.modules.feedback.application.views import FeedbackPresenter, FeedbackView
from app.modules.feedback.domain.errors import FeedbackNotFoundError
from app.modules.feedback.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class GetMyFeedback:
    """Someone else's item is answered like a missing one."""

    def __init__(
        self, *, uow_factory: UowFactory, presenter: FeedbackPresenter
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._presenter = presenter

    async def execute(self, actor: Actor, feedback_id: UUID) -> FeedbackView:
        """Return the item.

        Raises:
            FeedbackNotFoundError: Missing or not the actor's.
        """
        async with self._uow_factory() as uow:
            item = await uow.feedback.get(feedback_id)
            if item is None or item.reporter_id != actor.user_id:
                raise FeedbackNotFoundError()
            responses = await uow.feedback.responses(feedback_id)
        return await self._presenter.detail(item, responses)

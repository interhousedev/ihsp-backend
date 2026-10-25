"""The caller's own feedback, newest first."""

from app.modules.feedback.application.views import FeedbackPresenter, FeedbackView
from app.modules.feedback.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class ListMyFeedback:
    """Every item the actor sent."""

    def __init__(
        self, *, uow_factory: UowFactory, presenter: FeedbackPresenter
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._presenter = presenter

    async def execute(self, actor: Actor) -> list[FeedbackView]:
        """Return the actor's items."""
        async with self._uow_factory() as uow:
            items = await uow.feedback.list_for_reporter(actor.user_id)
        return await self._presenter.items(items)

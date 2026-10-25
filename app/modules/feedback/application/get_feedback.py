"""One feedback item for administrators, with the reporter and responses."""

from uuid import UUID

from app.modules.feedback.application.views import FeedbackPresenter, FeedbackView
from app.modules.feedback.domain.errors import FeedbackNotFoundError
from app.modules.feedback.ports.unit_of_work import UowFactory


class GetFeedback:
    """Read any item."""

    def __init__(
        self, *, uow_factory: UowFactory, presenter: FeedbackPresenter
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._presenter = presenter

    async def execute(self, feedback_id: UUID) -> FeedbackView:
        """Return the item.

        Raises:
            FeedbackNotFoundError: No such item.
        """
        async with self._uow_factory() as uow:
            item = await uow.feedback.get(feedback_id)
            if item is None:
                raise FeedbackNotFoundError()
            responses = await uow.feedback.responses(feedback_id)
        return await self._presenter.detail(item, responses, with_reporter=True)

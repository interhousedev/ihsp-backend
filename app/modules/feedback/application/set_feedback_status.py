"""Change the review status of a feedback item (administrator)."""

from uuid import UUID

from app.modules.feedback.application.get_feedback import GetFeedback
from app.modules.feedback.application.views import FeedbackView
from app.modules.feedback.domain.errors import FeedbackNotFoundError
from app.modules.feedback.domain.feedback import FeedbackStatus, parse_enum
from app.modules.feedback.ports.unit_of_work import UowFactory
from app.shared.clock import Clock


class SetFeedbackStatus:
    """Any status may follow any other."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, get: GetFeedback
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._get = get

    async def execute(
        self, feedback_id: UUID, status: FeedbackStatus | str
    ) -> FeedbackView:
        """Store the status and return the detail.

        Raises:
            FeedbackInvalidError: Unknown status.
            FeedbackNotFoundError: No such item.
        """
        value = parse_enum(FeedbackStatus, status, "status")
        async with self._uow_factory() as uow:
            if await uow.feedback.get(feedback_id) is None:
                raise FeedbackNotFoundError()
            await uow.feedback.set_status(feedback_id, value, self._clock.now())
            await uow.commit()
        return await self._get.execute(feedback_id)

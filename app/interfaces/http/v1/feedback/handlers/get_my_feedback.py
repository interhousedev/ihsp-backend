"""GET /v1/feedback/{feedback_id}."""

from uuid import UUID

from app.interfaces.http.v1.feedback.deps import ContainerDep, UserActor
from app.interfaces.http.v1.feedback.schemas import FeedbackDetailOut


async def get_my_feedback(
    feedback_id: UUID, container: ContainerDep, actor: UserActor
) -> FeedbackDetailOut:
    """One of the caller's items with responses; anyone else's answers 404."""
    view = await container.feedback.get_mine.execute(actor, feedback_id)
    return FeedbackDetailOut.of(view)

"""GET /v1/feedback/mine."""

from app.interfaces.http.v1.feedback.deps import ContainerDep, UserActor
from app.interfaces.http.v1.feedback.schemas import FeedbackListOut, FeedbackOut


async def list_my_feedback(
    container: ContainerDep, actor: UserActor
) -> FeedbackListOut:
    """The caller's feedback, newest first."""
    views = await container.feedback.list_mine.execute(actor)
    return FeedbackListOut(items=[FeedbackOut.of(view) for view in views])

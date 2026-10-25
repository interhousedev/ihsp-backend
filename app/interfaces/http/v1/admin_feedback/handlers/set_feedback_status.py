"""PATCH /v1/admin/feedback/{feedback_id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_feedback.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.feedback.schemas import (
    AdminFeedbackDetail,
    FeedbackStatusIn,
)


async def set_feedback_status(
    feedback_id: UUID,
    body: FeedbackStatusIn,
    container: ContainerDep,
    actor: AdminActor,
) -> AdminFeedbackDetail:
    """Change the review status."""
    view = await container.feedback.set_status.execute(feedback_id, body.status)
    return AdminFeedbackDetail.of(view)

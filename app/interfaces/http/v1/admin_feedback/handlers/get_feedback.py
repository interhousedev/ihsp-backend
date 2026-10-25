"""GET /v1/admin/feedback/{feedback_id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_feedback.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.feedback.schemas import AdminFeedbackDetail


async def get_feedback(
    feedback_id: UUID, container: ContainerDep, actor: AdminActor
) -> AdminFeedbackDetail:
    """One item with its reporter and responses."""
    return AdminFeedbackDetail.of(await container.feedback.get.execute(feedback_id))

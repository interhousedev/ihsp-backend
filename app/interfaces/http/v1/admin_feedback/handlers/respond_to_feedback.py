"""POST /v1/admin/feedback/{feedback_id}/responses."""

from uuid import UUID

from app.interfaces.http.v1.admin_feedback.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.feedback.schemas import ResponseIn, ResponseOut


async def respond_to_feedback(
    feedback_id: UUID, body: ResponseIn, container: ContainerDep, actor: AdminActor
) -> ResponseOut:
    """Answer by Telegram and/or mail; a missing channel is ``unavailable``."""
    view = await container.feedback.respond.execute(
        actor,
        feedback_id,
        text=body.text,
        channels=body.channels,
        attachment_file_ids=body.attachment_file_ids,
    )
    return ResponseOut.of(view)

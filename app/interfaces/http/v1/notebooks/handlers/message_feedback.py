"""POST /v1/notebooks/{id}/chat/messages/{mid}/feedback."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_chat import FeedbackBody

from fastapi import Response, status


async def message_feedback(
    notebook_id: UUID,
    message_id: UUID,
    body: FeedbackBody,
    actor: MemberActor,
    notebooks: Notebooks,
) -> Response:
    """Rate an answer with a thumb up or down."""
    await notebooks.message_feedback.execute(
        actor, notebook_id, message_id, body.rating, body.comment
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""POST /v1/ai/chats/{id}/messages/{seq}/feedback."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.schemas import MessageFeedbackBody
from app.modules.ai.domain.chat import Feedback
from app.shared.actor import Actor

from fastapi import Depends, Path, Response, status


async def set_message_feedback(
    chat_id: UUID,
    seq: Annotated[int, Path(ge=1)],
    body: MessageFeedbackBody,
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
) -> Response:
    """Rate an assistant message with a thumb and an optional comment."""
    await container.ai.set_message_feedback.execute(
        actor=actor,
        chat_id=chat_id,
        seq=seq,
        rating=Feedback(body.rating),
        comment=body.comment,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

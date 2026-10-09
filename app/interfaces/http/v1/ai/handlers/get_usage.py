"""GET /v1/ai/usage."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.schemas import AssistantName, UsageInfoResponse
from app.modules.ai.domain.assistant import Assistant
from app.shared.actor import Actor

from fastapi import Depends, Query


async def get_usage(
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
    assistant: Annotated[AssistantName | None, Query()] = None,
    course_id: UUID | None = None,
) -> UsageInfoResponse:
    """Return the remaining session and daily token budget.

    For `lms_author` (the course staff pool) pass the `course_id` being edited.
    """
    chosen = Assistant(assistant) if assistant else None
    usage = await container.ai.get_usage.execute(
        actor=actor, assistant=chosen, course_id=course_id
    )
    return UsageInfoResponse.from_view(usage)

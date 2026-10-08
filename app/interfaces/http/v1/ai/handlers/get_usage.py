"""GET /v1/ai/usage."""

from typing import Annotated

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
) -> UsageInfoResponse:
    """Return the remaining session and daily token budget."""
    chosen = Assistant(assistant) if assistant else None
    usage = await container.ai.get_usage.execute(actor=actor, assistant=chosen)
    return UsageInfoResponse.from_view(usage)

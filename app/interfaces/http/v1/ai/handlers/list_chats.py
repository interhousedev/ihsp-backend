"""GET /v1/ai/chats."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.ai.schemas import AssistantName, ChatItemResponse
from app.modules.ai.domain.assistant import Assistant, default_assistant
from app.shared.actor import Actor
from app.shared.pagination import Page

from fastapi import Depends, Query


async def list_chats(
    container: Annotated[Container, Depends(get_container)],
    actor: Annotated[Actor, Depends(get_actor)],
    assistant: Annotated[AssistantName | None, Query()] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    course_id: UUID | None = None,
) -> Page[ChatItemResponse]:
    """List the caller's chats of one assistant, newest first; `q` searches titles.

    `lms_author` chats are listed per course: `course_id` is required for them.
    """
    chosen = Assistant(assistant) if assistant else default_assistant(actor)
    page = await container.ai.list_chats.execute(
        actor=actor,
        assistant=chosen,
        cursor=cursor,
        limit=limit,
        q=q,
        course_id=course_id,
    )
    return Page(
        items=[ChatItemResponse.from_view(v) for v in page.items],
        next_cursor=page.next_cursor,
    )

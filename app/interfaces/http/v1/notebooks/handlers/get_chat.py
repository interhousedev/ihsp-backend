"""GET /v1/notebooks/{id}/chat."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_chat import ChatHistoryResponse


async def get_chat(
    notebook_id: UUID, actor: MemberActor, notebooks: Notebooks
) -> ChatHistoryResponse:
    """The last 200 messages of the student's thread, oldest first."""
    messages = await notebooks.get_chat.execute(actor, notebook_id)
    return ChatHistoryResponse.from_entities(messages)

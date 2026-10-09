"""POST /v1/notebooks/{id}/chat/messages/{mid}/save-note."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_chat import SaveNoteBody
from app.interfaces.http.v1.notebooks.schemas_common import SourceItemResponse


async def save_note(
    notebook_id: UUID,
    message_id: UUID,
    actor: MemberActor,
    notebooks: Notebooks,
    body: SaveNoteBody | None = None,
) -> SourceItemResponse:
    """Save an answer, with its citations, as a `note` source."""
    title = body.title if body is not None else None
    source = await notebooks.save_note.execute(actor, notebook_id, message_id, title)
    return SourceItemResponse.from_entity(source)

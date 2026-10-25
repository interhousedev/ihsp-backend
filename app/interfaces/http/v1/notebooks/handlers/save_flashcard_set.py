"""POST /v1/notebooks/{id}/artifacts/{aid}/flashcard-set."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import FlashcardSetResponse


async def save_flashcard_set(
    notebook_id: UUID,
    artifact_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
) -> FlashcardSetResponse:
    """Copy a deck into the student's flash card sets (once per deck)."""
    set_id, created = await notebooks.save_flashcard_set.execute(
        actor, notebook_id, artifact_id
    )
    return FlashcardSetResponse(set_id=set_id, created=created)

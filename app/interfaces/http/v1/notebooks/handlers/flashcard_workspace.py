"""POST /v1/notebooks/flashcard-workspace."""

from app.interfaces.http.v1.notebooks.deps import Notebooks, OwnerActor
from app.interfaces.http.v1.notebooks.schemas_sources import (
    FlashcardWorkspaceBody,
    FlashcardWorkspaceResponse,
)


async def flashcard_workspace(
    body: FlashcardWorkspaceBody, notebooks: Notebooks, actor: OwnerActor
) -> FlashcardWorkspaceResponse:
    """Put the chosen notebook sources and files into the hidden Studio notebook."""
    result = await notebooks.flashcard_workspace.execute(
        actor,
        [(item.notebook_id, item.source_id) for item in body.notebook_sources],
        body.file_ids,
    )
    return FlashcardWorkspaceResponse.from_result(result)

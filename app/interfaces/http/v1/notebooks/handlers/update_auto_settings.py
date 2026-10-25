"""PATCH /v1/notebooks/{id}/auto."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import Notebooks, StudentActor
from app.interfaces.http.v1.notebooks.schemas_notebooks import (
    NotebookDetailResponse,
    UpdateAutoSettingsBody,
)


async def update_auto_settings(
    notebook_id: UUID,
    body: UpdateAutoSettingsBody,
    notebooks: Notebooks,
    actor: StudentActor,
) -> NotebookDetailResponse:
    """Switch classmates' files on or off, exclude or restore materials; syncs now."""
    notebook = await notebooks.update_auto_settings.execute(
        actor, notebook_id, body.model_dump(exclude_unset=True)
    )
    return NotebookDetailResponse.from_entity(notebook)

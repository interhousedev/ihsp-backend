"""PATCH /v1/notebooks/{id}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_notebooks import (
    NotebookDetailResponse,
    UpdateNotebookBody,
)


async def update_notebook(
    notebook_id: UUID,
    body: UpdateNotebookBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> NotebookDetailResponse:
    """Rename, pin or configure a notebook; keys that were not sent are kept."""
    notebook = await notebooks.update_notebook.execute(
        actor, notebook_id, body.model_dump(exclude_unset=True)
    )
    return NotebookDetailResponse.from_entity(notebook)

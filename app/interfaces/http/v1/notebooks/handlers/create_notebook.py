"""POST /v1/notebooks."""

from app.interfaces.http.v1.notebooks.deps import Notebooks, StudentActor
from app.interfaces.http.v1.notebooks.schemas_notebooks import (
    CreateNotebookBody,
    NotebookDetailResponse,
)


async def create_notebook(
    body: CreateNotebookBody, notebooks: Notebooks, actor: StudentActor
) -> NotebookDetailResponse:
    """Create a notebook; without a title it is "Untitled notebook"."""
    notebook = await notebooks.create_notebook.execute(
        actor, title=body.title, emoji=body.emoji
    )
    return NotebookDetailResponse.from_entity(notebook)

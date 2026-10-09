"""POST /v1/notebooks/{id}/copy."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import Notebooks, StudentActor
from app.interfaces.http.v1.notebooks.schemas_notebooks import NotebookDetailResponse


async def copy_notebook(
    notebook_id: UUID, notebooks: Notebooks, actor: StudentActor
) -> NotebookDetailResponse:
    """Copy a notebook with its sources into a normal, editable notebook."""
    notebook = await notebooks.copy_notebook.execute(actor, notebook_id)
    return NotebookDetailResponse.from_entity(notebook)

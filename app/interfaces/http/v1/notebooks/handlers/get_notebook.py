"""GET /v1/notebooks/{id}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_notebooks import NotebookDetailResponse


async def get_notebook(
    notebook_id: UUID, notebooks: Notebooks, actor: MemberActor
) -> NotebookDetailResponse:
    """Open a notebook of the student (it becomes the last opened)."""
    notebook = await notebooks.get_notebook.execute(actor, notebook_id)
    return NotebookDetailResponse.from_entity(notebook)

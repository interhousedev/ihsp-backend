"""GET /v1/notebooks/auto/subject/{subject_id}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import Notebooks, OwnerActor
from app.interfaces.http.v1.notebooks.schemas_notebooks import NotebookDetailResponse
from app.modules.notebooks.domain.enums import NotebookOrigin


async def find_subject_notebook(
    subject_id: UUID,
    notebooks: Notebooks,
    actor: OwnerActor,
    group_id: UUID | None = None,
) -> NotebookDetailResponse:
    """The user's notebook of a subject (and group) if it exists; read-only."""
    notebook = await notebooks.open_auto_notebook.execute(
        actor,
        NotebookOrigin.SUBJECT_AUTO,
        subject_id,
        create=False,
        group_id=group_id,
    )
    return NotebookDetailResponse.from_entity(notebook)

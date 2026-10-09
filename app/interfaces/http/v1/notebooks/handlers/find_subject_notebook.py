"""GET /v1/notebooks/auto/subject/{subject_id}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import Notebooks, StudentActor
from app.interfaces.http.v1.notebooks.schemas_notebooks import NotebookDetailResponse
from app.modules.notebooks.domain.enums import NotebookOrigin


async def find_subject_notebook(
    subject_id: UUID, notebooks: Notebooks, actor: StudentActor
) -> NotebookDetailResponse:
    """The student's notebook of a subject if it exists (404 otherwise); read-only."""
    notebook = await notebooks.open_auto_notebook.execute(
        actor, NotebookOrigin.SUBJECT_AUTO, subject_id, create=False
    )
    return NotebookDetailResponse.from_entity(notebook)

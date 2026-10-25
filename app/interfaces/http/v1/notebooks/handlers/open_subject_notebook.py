"""POST /v1/notebooks/auto/subject/{subject_id}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import Notebooks, OwnerActor
from app.interfaces.http.v1.notebooks.schemas_notebooks import NotebookDetailResponse
from app.modules.notebooks.domain.enums import NotebookOrigin


async def open_subject_notebook(
    subject_id: UUID,
    notebooks: Notebooks,
    actor: OwnerActor,
    group_id: UUID | None = None,
) -> NotebookDetailResponse:
    """Get or create the user's notebook of a subject (this term's materials).

    A teacher adds the `group_id` they teach the subject to; a student does not.
    Safe to call twice at once: one notebook is made.
    """
    notebook = await notebooks.open_auto_notebook.execute(
        actor, NotebookOrigin.SUBJECT_AUTO, subject_id, group_id=group_id
    )
    return NotebookDetailResponse.from_entity(notebook)

"""GET /v1/notebooks/auto/subjects."""

from app.interfaces.http.v1.notebooks.deps import Notebooks, OwnerActor
from app.interfaces.http.v1.notebooks.schemas_notebooks import (
    SubjectNotebookSlotResponse,
)


async def list_subject_slots(
    notebooks: Notebooks, actor: OwnerActor
) -> list[SubjectNotebookSlotResponse]:
    """A slot for every subject (teachers: subject and group) the user has.

    `notebook_id` is null until the first open creates the notebook.
    """
    slots = await notebooks.list_subject_slots.execute(actor)
    return [
        SubjectNotebookSlotResponse(
            subject_id=x.subject_id,
            subject_name=x.subject_name,
            group_id=x.group_id,
            group_name=x.group_name,
            notebook_id=x.notebook_id,
            source_count=x.source_count,
        )
        for x in slots
    ]

"""PUT /v1/notebooks/{id}/sources/{sid}/labels."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_common import SourceItemResponse
from app.interfaces.http.v1.notebooks.schemas_labels import SetSourceLabelsBody


async def set_source_labels(
    notebook_id: UUID,
    source_id: UUID,
    body: SetSourceLabelsBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> SourceItemResponse:
    """Replace the labels of a source (at most 3); the automatic run keeps them."""
    source = await notebooks.set_source_labels.execute(
        actor, notebook_id, source_id, body.label_ids
    )
    return SourceItemResponse.from_entity(source)

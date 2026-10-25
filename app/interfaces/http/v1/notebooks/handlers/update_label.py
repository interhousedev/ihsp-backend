"""PATCH /v1/notebooks/{id}/labels/{label_id}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_labels import (
    LabelItemResponse,
    UpdateLabelBody,
)


async def update_label(
    notebook_id: UUID,
    label_id: UUID,
    body: UpdateLabelBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> LabelItemResponse:
    """Rename a label or change its emoji; an edited auto label becomes manual."""
    label = await notebooks.update_label.execute(
        actor, notebook_id, label_id, body.model_dump(exclude_unset=True)
    )
    return LabelItemResponse.from_entity(label)

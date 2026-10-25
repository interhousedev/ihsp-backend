"""POST /v1/notebooks/{id}/labels."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_labels import (
    CreateLabelBody,
    LabelItemResponse,
)


async def create_label(
    notebook_id: UUID,
    body: CreateLabelBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> LabelItemResponse:
    """Make a label by hand (at most 12 per notebook)."""
    label = await notebooks.create_label.execute(
        actor, notebook_id, body.name, body.emoji
    )
    return LabelItemResponse.from_entity(label)

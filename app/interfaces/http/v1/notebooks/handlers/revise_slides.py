"""POST /v1/notebooks/{id}/artifacts/{aid}/slides/revise."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import (
    ArtifactItemResponse,
    ReviseSlidesBody,
)


async def revise_slides(
    notebook_id: UUID,
    artifact_id: UUID,
    body: ReviseSlidesBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> ArtifactItemResponse:
    """Queue a new deck in which only the named slides are rewritten."""
    revision = await notebooks.revise_slides.execute(
        actor,
        notebook_id,
        artifact_id,
        [change.model_dump() for change in body.changes],
    )
    return ArtifactItemResponse.from_entity(revision)

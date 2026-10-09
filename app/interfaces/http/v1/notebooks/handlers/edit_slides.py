"""PUT /v1/notebooks/{id}/artifacts/{aid}/slides."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import (
    ArtifactDetailResponse,
    SlidesBody,
)


async def edit_slides(
    notebook_id: UUID,
    artifact_id: UUID,
    body: SlidesBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> ArtifactDetailResponse:
    """Save the student's edits of a slide deck (text, order, deleted slides)."""
    view = await notebooks.edit_slides.execute(
        actor, notebook_id, artifact_id, body.slides
    )
    return ArtifactDetailResponse.from_view(view)

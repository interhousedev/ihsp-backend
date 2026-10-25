"""GET /v1/notebooks/{id}/artifacts/{aid}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import ArtifactDetailResponse


async def get_artifact(
    notebook_id: UUID,
    artifact_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
) -> ArtifactDetailResponse:
    """Open an output with its content; the first view clears the blue dot."""
    view = await notebooks.get_artifact.execute(actor, notebook_id, artifact_id)
    return ArtifactDetailResponse.from_view(view)

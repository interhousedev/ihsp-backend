"""POST /v1/notebooks/{id}/artifacts/{aid}/cancel."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import ArtifactItemResponse


async def cancel_artifact(
    notebook_id: UUID,
    artifact_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
) -> ArtifactItemResponse:
    """Stop an output that is queued or generating."""
    artifact = await notebooks.cancel_artifact.execute(actor, notebook_id, artifact_id)
    return ArtifactItemResponse.from_entity(artifact)

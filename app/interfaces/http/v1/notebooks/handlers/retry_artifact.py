"""POST /v1/notebooks/{id}/artifacts/{aid}/retry."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import ArtifactItemResponse


async def retry_artifact(
    notebook_id: UUID,
    artifact_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
) -> ArtifactItemResponse:
    """Queue a failed or canceled output again."""
    artifact = await notebooks.retry_artifact.execute(actor, notebook_id, artifact_id)
    return ArtifactItemResponse.from_entity(artifact)

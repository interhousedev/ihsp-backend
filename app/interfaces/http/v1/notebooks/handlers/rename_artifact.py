"""PATCH /v1/notebooks/{id}/artifacts/{aid}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import (
    ArtifactItemResponse,
    RenameArtifactBody,
)


async def rename_artifact(
    notebook_id: UUID,
    artifact_id: UUID,
    body: RenameArtifactBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> ArtifactItemResponse:
    """Change the title of an output."""
    artifact = await notebooks.rename_artifact.execute(
        actor, notebook_id, artifact_id, body.title
    )
    return ArtifactItemResponse.from_entity(artifact)

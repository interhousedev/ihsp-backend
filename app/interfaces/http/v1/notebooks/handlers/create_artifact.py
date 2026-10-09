"""POST /v1/notebooks/{id}/artifacts."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import (
    ArtifactCreate,
    ArtifactItemResponse,
)


async def create_artifact(
    notebook_id: UUID,
    body: ArtifactCreate,
    notebooks: Notebooks,
    actor: MemberActor,
) -> ArtifactItemResponse:
    """Queue a Studio output; the job generates it in the background."""
    artifact = await notebooks.request_artifact.execute(
        actor, notebook_id, body.kind, body.options_dict(), body.prompt
    )
    return ArtifactItemResponse.from_entity(artifact)

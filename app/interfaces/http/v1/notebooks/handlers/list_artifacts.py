"""GET /v1/notebooks/{id}/artifacts."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import (
    ArtifactItemResponse,
    StudioKind,
)
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus


async def list_artifacts(
    notebook_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
    kind: StudioKind | None = None,
    status: ArtifactStatus | None = None,
) -> list[ArtifactItemResponse]:
    """The outputs of a notebook, newest first, without their content."""
    artifacts = await notebooks.list_artifacts.execute(
        actor,
        notebook_id,
        kind=ArtifactKind(kind) if kind else None,
        status=status,
    )
    return [ArtifactItemResponse.from_entity(artifact) for artifact in artifacts]

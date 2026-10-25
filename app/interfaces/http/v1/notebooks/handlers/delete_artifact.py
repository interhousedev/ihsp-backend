"""DELETE /v1/notebooks/{id}/artifacts/{aid}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks

from fastapi import Response, status


async def delete_artifact(
    notebook_id: UUID,
    artifact_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
) -> Response:
    """Delete an output."""
    await notebooks.delete_artifact.execute(actor, notebook_id, artifact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

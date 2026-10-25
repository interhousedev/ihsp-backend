"""PUT /v1/notebooks/{id}/artifacts/{aid}/progress."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import ProgressBody

from fastapi import Response, status


async def save_progress(
    notebook_id: UUID,
    artifact_id: UUID,
    body: ProgressBody,
    notebooks: Notebooks,
    actor: MemberActor,
) -> Response:
    """Remember where the student stopped in a flash card deck or a quiz."""
    await notebooks.save_progress.execute(actor, notebook_id, artifact_id, body.state)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

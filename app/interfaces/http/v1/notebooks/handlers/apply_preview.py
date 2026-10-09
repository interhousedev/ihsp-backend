"""POST /v1/notebooks/{id}/artifacts/{aid}/apply-preview."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.notebooks.deps import Notebooks
from app.interfaces.http.v1.notebooks.schemas_apply import (
    ApplyBody,
    ApplyPreviewResponse,
)
from app.shared.actor import Actor

from fastapi import Depends


async def apply_preview(
    notebook_id: UUID,
    artifact_id: UUID,
    body: ApplyBody,
    notebooks: Notebooks,
    actor: Annotated[Actor, Depends(get_actor)],
) -> ApplyPreviewResponse:
    """Dry run: what applying the output to the course draft would change.

    Needs the `edit` permission on the course. Nothing is written.
    """
    view = await notebooks.apply_course_artifact.preview(
        actor, notebook_id, artifact_id, body.to_request()
    )
    return ApplyPreviewResponse.from_view(view)

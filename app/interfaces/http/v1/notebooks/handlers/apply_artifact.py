"""POST /v1/notebooks/{id}/artifacts/{aid}/apply."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.notebooks.deps import Notebooks
from app.interfaces.http.v1.notebooks.schemas_apply import (
    ApplyBody,
    ApplyResultResponse,
)
from app.shared.actor import Actor

from fastapi import Depends


async def apply_artifact(
    notebook_id: UUID,
    artifact_id: UUID,
    body: ApplyBody,
    notebooks: Notebooks,
    actor: Annotated[Actor, Depends(get_actor)],
) -> ApplyResultResponse:
    """Write the output into the course draft; nothing goes live before Publish.

    Needs the `edit` permission on the course. A stale `lock_version` is 409
    (`common/conflict`), invalid content 422 (`lms/content-invalid` or
    `notebooks/output-invalid`).
    """
    view = await notebooks.apply_course_artifact.apply(
        actor, notebook_id, artifact_id, body.to_request()
    )
    return ApplyResultResponse.from_view(view)

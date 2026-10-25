"""DELETE /v1/admin/subject-materials/{edu_subject_id}/{material_id}."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import AdminActor, Notebooks

from fastapi import Path, Response, status


async def remove_default_material(
    edu_subject_id: Annotated[int, Path(ge=1)],
    material_id: UUID,
    notebooks: Notebooks,
    actor: AdminActor,
) -> Response:
    """Remove a default material; the copies students have follow on their sync."""
    await notebooks.remove_default_material.execute(edu_subject_id, material_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

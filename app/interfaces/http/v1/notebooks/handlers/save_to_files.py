"""POST /v1/notebooks/{id}/artifacts/{aid}/save-to-files."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_studio import (
    SavedFileResponse,
    SaveToFilesBody,
)
from app.modules.notebooks.domain.errors import FeatureDisabledError


async def save_to_files(
    notebook_id: UUID,
    artifact_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
    body: SaveToFilesBody | None = None,
) -> SavedFileResponse:
    """Save a copy of a ready output as a file in "My files"."""
    use_case = notebooks.save_to_files
    if use_case is None:
        raise FeatureDisabledError(params={"feature": "save-to-files"})
    file = await use_case.execute(
        actor, notebook_id, artifact_id, body.format if body else None
    )
    return SavedFileResponse(
        id=file.id,
        name=file.name,
        content_type=file.content_type,
        byte_size=file.byte_size,
    )

"""POST /v1/admin/students/import."""

from typing import Annotated

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.students.schemas import (
    ImportPreviewResponse,
)
from app.modules.academic.domain.schedule.errors import ImportInvalidError

from fastapi import File, UploadFile

MAX_BYTES = 2 * 1024 * 1024


async def import_preview(
    file: Annotated[UploadFile, File()], container: ContainerDep, actor: AdminActor
) -> ImportPreviewResponse:
    """Read the CSV and return what confirming it would do."""
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ImportInvalidError(params={"reason": "too-large"})
    preview = await container.academic.schedule.import_preview.execute(data)
    return ImportPreviewResponse.from_data(preview)

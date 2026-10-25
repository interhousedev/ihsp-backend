"""POST /v1/certificates/staff/export."""

from app.interfaces.http.v1.certificates.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.certificates.schemas import ExportBody

from fastapi.responses import StreamingResponse

ARCHIVE_NAME = "certificates.zip"


async def export_entries(
    body: ExportBody, container: ContainerDep, actor: StaffActor
) -> StreamingResponse:
    """Stream the chosen certificate files as a ZIP archive."""
    export = container.certificates.export_entries
    filters = body.filters.to_filters() if body.filters else None
    items = await export.plan(actor, file_ids=body.file_ids, filters=filters)
    return StreamingResponse(
        export.stream(items),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{ARCHIVE_NAME}"'},
    )

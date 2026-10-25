"""POST /v1/manage/library/reports/{id}/resolve."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import LibrarianActor, Library
from app.interfaces.http.v1.library.materials.schemas_moderation import (
    ReportResolveBody,
)

from fastapi import Response, status


async def resolve_report(
    report_id: UUID, body: ReportResolveBody, library: Library, actor: LibrarianActor
) -> Response:
    """Decide every open report of the item the report belongs to."""
    await library.materials.resolve_report.execute(actor, report_id, body.action)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

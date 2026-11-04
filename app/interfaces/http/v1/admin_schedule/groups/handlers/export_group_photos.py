"""GET /v1/admin/groups/{id}/photos.zip: group photos as one ZIP (ADM-PHOTO-2)."""

import asyncio
from collections.abc import AsyncIterator
from typing import IO
from urllib.parse import quote
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep

from fastapi import Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

CHUNK_BYTES = 256 * 1024


async def _chunks(fp: IO[bytes]) -> AsyncIterator[bytes]:
    """Stream the spooled archive; the reads run off the event loop."""
    while chunk := await asyncio.to_thread(fp.read, CHUNK_BYTES):
        yield chunk


async def export_group_photos(
    group_id: UUID, container: ContainerDep, actor: AdminActor
) -> Response:
    """Return the group's active students' photos as a ZIP, named by full name."""
    archive = await container.academic.schedule.export_group_photos.execute(
        actor, group_id
    )
    return StreamingResponse(
        _chunks(archive.fp),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                'attachment; filename="group-photos.zip"; '
                f"filename*=UTF-8''{quote(archive.filename)}"
            ),
            "X-Photos-Exported": str(archive.exported),
            "X-Photos-Missing": str(len(archive.missing)),
        },
        background=BackgroundTask(archive.fp.close),
    )

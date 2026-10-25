"""GET /v1/notebooks/{id}/sources/{sid}/file-url: a link to the file behind a source."""

from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_sources import SourceFileUrlResponse

from fastapi import Query


async def get_source_file_url(
    notebook_id: UUID,
    source_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
    disposition: Annotated[Literal["inline", "attachment"] | None, Query()] = None,
) -> SourceFileUrlResponse:
    """Presign a GET of the uploaded file; access is the access to the notebook.

    Only PDFs and images may be shown inline; `404` when the source has no file.
    """
    result = await notebooks.get_source.file_url(
        actor, notebook_id, source_id, disposition
    )
    return SourceFileUrlResponse(url=result.url, expires_at=result.expires_at)

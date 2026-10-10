"""GET /v1/notebooks/{id}/artifacts/{aid}/download."""

from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.modules.notebooks.application.export.render import (
    export_artifact,
    format_for,
)
from app.modules.notebooks.domain.enums import ArtifactStatus
from app.modules.notebooks.domain.errors import (
    ArtifactNotReadyError,
    InvalidOptionsError,
)

from fastapi import Query, Response


async def download_artifact(
    notebook_id: UUID,
    artifact_id: UUID,
    notebooks: Notebooks,
    actor: MemberActor,
    format: Annotated[  # noqa: A002 - the query parameter is called "format"
        Literal["docx", "xlsx", "pptx"] | None, Query()
    ] = None,
) -> Response:
    """Download a ready output as a file: report .docx, table .xlsx, slides .pptx."""
    view = await notebooks.get_artifact.execute(actor, notebook_id, artifact_id)
    artifact = view.artifact
    wanted = format_for(artifact.kind)
    if wanted is None or (format is not None and format != wanted):
        raise InvalidOptionsError(
            params={"kind": artifact.kind.value, "format": format or ""}
        )
    if artifact.status is not ArtifactStatus.READY or not artifact.content:
        raise ArtifactNotReadyError()
    document = export_artifact(artifact.kind, artifact.title, artifact.content)
    ascii_name = document.name.encode("ascii", "ignore").decode() or f"file.{wanted}"
    disposition = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(document.name)}"
    )
    return Response(
        content=document.data,
        media_type=document.content_type,
        headers={"Content-Disposition": disposition},
    )

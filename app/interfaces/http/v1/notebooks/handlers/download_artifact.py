"""GET /v1/notebooks/{id}/artifacts/{aid}/download."""

from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, Notebooks
from app.modules.notebooks.application.export.render import (
    default_format,
    export_as,
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
        Literal["docx", "xlsx", "pptx", "md", "json"] | None, Query()
    ] = None,
) -> Response:
    """Download a ready output: report .docx, table .xlsx, slides .pptx, the rest .md.

    Every kind can also be asked for as ``json``.
    """
    view = await notebooks.get_artifact.execute(actor, notebook_id, artifact_id)
    artifact = view.artifact
    wanted = format or default_format(artifact.kind)
    if wanted is None:
        raise InvalidOptionsError(
            params={"kind": artifact.kind.value, "format": format or ""}
        )
    if artifact.status is not ArtifactStatus.READY or not artifact.content:
        raise ArtifactNotReadyError()
    try:
        document = export_as(artifact.kind, artifact.title, artifact.content, wanted)
    except ValueError as error:
        raise InvalidOptionsError(
            params={"kind": artifact.kind.value, "format": wanted}
        ) from error
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

"""Use case: save a copy of a ready Studio output into the student's files."""

from uuid import UUID

from app.modules.notebooks.application.access import load_artifact
from app.modules.notebooks.application.artifact_engine import require_ready
from app.modules.notebooks.application.export.render import (
    KIND_FORMATS,
    default_format,
    export_as,
)
from app.modules.notebooks.application.export.text import TEXT_KINDS
from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose, FileRef, FilesApi, FileScope

_STAFF = frozenset({Role.TEACHER, Role.ADMIN, Role.LMS_ADMIN, Role.LMS_CREATOR})


class SaveArtifactToFiles:
    """Renders the output (Office or Markdown) and stores it as the caller's file."""

    def __init__(self, *, uow_factory: UowFactory, files: FilesApi) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.files = files

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        artifact_id: UUID,
        fmt: str | None = None,
    ) -> FileRef:
        """Store the file; JSON is not an allowed file type, so it is refused here.

        Raises:
            NotebookNotFoundError: Not the caller's notebook or output.
            InvalidOptionsError: The kind has no such format.
            ArtifactNotReadyError: The output is not ready.
        """
        async with self.uow_factory() as uow:
            artifact = await load_artifact(uow, actor.user_id, notebook_id, artifact_id)
        wanted = fmt or default_format(artifact.kind)
        if wanted is None or wanted == "json":
            raise InvalidOptionsError(
                params={"kind": artifact.kind.value, "format": fmt or ""}
            )
        content = require_ready(artifact, *KIND_FORMATS, *TEXT_KINDS)
        try:
            rendered = export_as(artifact.kind, artifact.title, content, wanted)
        except ValueError as error:
            raise InvalidOptionsError(
                params={"kind": artifact.kind.value, "format": wanted}
            ) from error
        scope = FileScope.STAFF if _STAFF & actor.roles else FileScope.STUDENT
        return await self.files.store_bytes(
            owner_id=actor.user_id,
            scope=scope,
            purpose=FilePurpose.AI_UPLOAD,
            name=rendered.name,
            data=rendered.data,
        )

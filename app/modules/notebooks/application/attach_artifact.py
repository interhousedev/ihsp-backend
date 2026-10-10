"""Use case: attach a ready Studio output to a lesson as a material (teachers)."""

from typing import Literal
from uuid import UUID

from app.modules.notebooks.application.access import load_artifact
from app.modules.notebooks.application.artifact_engine import require_ready
from app.modules.notebooks.application.export.render import (
    KIND_FORMATS,
    export_artifact,
)
from app.modules.notebooks.domain.entities import Artifact
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope
from app.shared.contracts.links import LinksApi, ResourceRef


class AttachArtifactToLesson:
    """Stores the output as an Office file and adds it to the lesson."""

    def __init__(
        self, *, uow_factory: UowFactory, files: FilesApi, links: LinksApi
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.files = files
        self.links = links

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        artifact_id: UUID,
        lesson_id: UUID,
        role: Literal["material", "attachment"] = "material",
    ) -> ResourceRef:
        """Render the output (a report as .docx, a table as .xlsx, slides as .pptx).

        Raises:
            ForbiddenError: The caller is not a teacher.
            NotebookNotFoundError: Not the caller's notebook or output.
            InvalidOptionsError: The kind has no file format.
            ArtifactNotReadyError: The output is not ready.
        """
        actor.require(Role.TEACHER)
        async with self.uow_factory() as uow:
            artifact = await load_artifact(uow, actor.user_id, notebook_id, artifact_id)
        content = require_ready(artifact, *KIND_FORMATS)
        rendered = export_artifact(artifact.kind, _title(artifact), content)
        stored = await self.files.store_bytes(
            owner_id=actor.user_id,
            scope=FileScope.STAFF,
            purpose=FilePurpose.LINK,
            name=rendered.name,
            data=rendered.data,
        )
        return await self.links.add_lesson_resource(
            actor, lesson_id, role=role, file_id=stored.id
        )


def _title(artifact: Artifact) -> str:
    """The name of the file: the title of the output."""
    return artifact.title

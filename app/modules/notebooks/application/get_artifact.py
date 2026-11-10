"""Use case: open one Studio output (the first view clears the blue dot)."""

from dataclasses import replace
from uuid import UUID

from app.modules.notebooks.application.access import load_artifact
from app.modules.notebooks.application.artifact_engine import detail_view
from app.modules.notebooks.application.slide_images import (
    load_image_bytes,
    sign_images,
)
from app.modules.notebooks.application.views import ArtifactDetailView
from app.modules.notebooks.domain.enums import ArtifactStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi


class GetArtifact:
    """Returns an output with its content and the student's progress."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, files: FilesApi | None = None
    ) -> None:
        """Store the collaborators; `files` signs the pictures of a slide deck."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.files = files

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        artifact_id: UUID,
        *,
        with_image_data: bool = False,
    ) -> ArtifactDetailView:
        """Return the output; set `viewed_at` on the first view of a ready one.

        Slide images get a presigned `url`; `with_image_data` also reads their bytes
        (for an export).

        Raises:
            NotebookNotFoundError: Not the student's notebook or output.
        """
        user_id = actor.user_id
        async with self.uow_factory() as uow:
            artifact = await load_artifact(
                uow, user_id, notebook_id, artifact_id, write=False
            )
            if artifact.status is ArtifactStatus.READY and artifact.viewed_at is None:
                artifact = await load_artifact(
                    uow, user_id, notebook_id, artifact_id, for_update=True, write=False
                )
                if artifact.viewed_at is None:
                    now = self.clock.now()
                    artifact.viewed_at = now
                    artifact.updated_at = now
                    await uow.artifacts.save(artifact)
                    await uow.commit()
            view = await detail_view(uow, artifact, user_id)
        content = view.artifact.content
        data = await load_image_bytes(self.files, content) if with_image_data else None
        signed = await sign_images(self.files, content)
        if signed is not content:
            view = replace(view, artifact=replace(view.artifact, content=signed))
        return replace(view, image_data=data)

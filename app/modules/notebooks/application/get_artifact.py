"""Use case: open one Studio output (the first view clears the blue dot)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_artifact
from app.modules.notebooks.application.artifact_engine import detail_view
from app.modules.notebooks.application.views import ArtifactDetailView
from app.modules.notebooks.domain.enums import ArtifactStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class GetArtifact:
    """Returns an output with its content and the student's progress."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self, actor: Actor, notebook_id: UUID, artifact_id: UUID
    ) -> ArtifactDetailView:
        """Return the output; set `viewed_at` on the first view of a ready one.

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
            return await detail_view(uow, artifact, user_id)

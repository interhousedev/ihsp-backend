"""Use case: delete a Studio output (soft delete)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_artifact, load_notebook
from app.modules.notebooks.application.artifact_engine import ACTIVE, mark_canceled
from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class DeleteArtifact:
    """Hides an output; a queued or generating one is canceled first."""

    def __init__(
        self, *, uow_factory: UowFactory, quota: QuotaService, clock: Clock
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.quota = quota
        self.clock = clock

    async def execute(self, actor: Actor, notebook_id: UUID, artifact_id: UUID) -> None:
        """Set `deleted_at`; the job of a running output drops its result.

        Raises:
            NotebookNotFoundError: Not the student's notebook or output.
        """
        async with self.uow_factory() as uow:
            notebook = await load_notebook(uow, actor.user_id, notebook_id)
            artifact = await load_artifact(
                uow, actor.user_id, notebook_id, artifact_id, for_update=True
            )
            now = self.clock.now()
            running = artifact.status in ACTIVE
            if running:
                mark_canceled(artifact, now)
            artifact.deleted_at = now
            artifact.updated_at = now
            await uow.artifacts.save(artifact)
            await uow.commit()
        if running:
            quota = self.quota.pool(notebook.is_course_workspace)
            await quota.finished(artifact.charged_to, artifact_id)

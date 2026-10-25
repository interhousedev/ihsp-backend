"""Use case: cancel an output that is queued or generating."""

from uuid import UUID

from app.modules.notebooks.application.access import load_artifact, load_notebook
from app.modules.notebooks.application.artifact_engine import ACTIVE, mark_canceled
from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.domain.entities import Artifact
from app.modules.notebooks.domain.errors import ArtifactNotReadyError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class CancelArtifact:
    """Stops an output; its job drops the result and the daily count comes back."""

    def __init__(
        self, *, uow_factory: UowFactory, quota: QuotaService, clock: Clock
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.quota = quota
        self.clock = clock

    async def execute(
        self, actor: Actor, notebook_id: UUID, artifact_id: UUID
    ) -> Artifact:
        """`queued` or `generating` -> `canceled`.

        Raises:
            NotebookNotFoundError: Not the student's notebook or output.
            ArtifactNotReadyError: The output is neither queued nor generating.
        """
        async with self.uow_factory() as uow:
            notebook = await load_notebook(uow, actor.user_id, notebook_id)
            artifact = await load_artifact(
                uow, actor.user_id, notebook_id, artifact_id, for_update=True
            )
            if artifact.status not in ACTIVE:
                raise ArtifactNotReadyError()
            mark_canceled(artifact, self.clock.now())
            await uow.artifacts.save(artifact)
            await uow.commit()
        # The count goes back to whoever asked for it (in a workspace: maybe not you).
        quota = self.quota.pool(notebook.is_course_workspace)
        await quota.finished(artifact.charged_to, artifact.id)
        await quota.release(artifact.charged_to, artifact.kind)
        return artifact

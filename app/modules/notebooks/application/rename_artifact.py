"""Use case: rename a Studio output."""

from uuid import UUID

from app.modules.notebooks.application.access import load_artifact
from app.modules.notebooks.domain.entities import Artifact
from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class RenameArtifact:
    """Changes the title of an output (any status)."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self, actor: Actor, notebook_id: UUID, artifact_id: UUID, title: str
    ) -> Artifact:
        """Set the title (1 to 200 characters after trimming).

        Raises:
            NotebookNotFoundError: Not the student's notebook or output.
            InvalidOptionsError: The title is empty or longer than 200 characters.
        """
        clean = " ".join(title.split())
        if not 1 <= len(clean) <= ARTIFACT_TITLE_MAX_CHARS:
            raise InvalidOptionsError(
                params={
                    "details": [f"title: 1 to {ARTIFACT_TITLE_MAX_CHARS} characters"]
                },
                support_details="bad title length",
            )
        async with self.uow_factory() as uow:
            artifact = await load_artifact(
                uow, actor.user_id, notebook_id, artifact_id, for_update=True
            )
            artifact.title = clean
            artifact.updated_at = self.clock.now()
            await uow.artifacts.save(artifact)
            await uow.commit()
        return artifact

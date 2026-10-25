"""Use case: the student edits a slide deck (titles, bullets, order, deleted slides)."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.application.access import load_artifact
from app.modules.notebooks.application.artifact_engine import (
    detail_view,
    require_ready,
)
from app.modules.notebooks.application.views import ArtifactDetailView
from app.modules.notebooks.domain.artifacts.slides_edit import validate_slides_edit
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import InvalidOptionsError, OutputInvalidError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class EditSlides:
    """Replaces the slides of a ready deck with the student's edited version."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        artifact_id: UUID,
        slides: list[dict[str, Any]],
    ) -> ArtifactDetailView:
        """Check the slides like generated ones and store them.

        Raises:
            NotebookNotFoundError: Not the student's notebook or output.
            InvalidOptionsError: The output is not a deck, or a slide is unusable.
            ArtifactNotReadyError: The deck is not ready.
        """
        async with self.uow_factory() as uow:
            artifact = await load_artifact(
                uow, actor.user_id, notebook_id, artifact_id, for_update=True
            )
            content = require_ready(artifact, ArtifactKind.SLIDES)
            try:
                checked = validate_slides_edit(slides, set(artifact.refs_index or {}))
            except OutputInvalidError as exc:
                raise InvalidOptionsError(
                    params={"details": exc.problems},
                    support_details=exc.support_details,
                ) from exc
            artifact.content = {**content, "slides": checked}
            artifact.updated_at = self.clock.now()
            await uow.artifacts.save(artifact)
            await uow.commit()
            return await detail_view(uow, artifact, actor.user_id)

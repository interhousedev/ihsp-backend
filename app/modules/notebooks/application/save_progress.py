"""Use case: save the student's progress in a flash card deck or a quiz."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.application.access import load_artifact
from app.modules.notebooks.application.artifact_engine import (
    content_bytes,
    require_ready,
)
from app.modules.notebooks.domain.entities import ArtifactProgress
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.modules.notebooks.domain.limits import PROGRESS_MAX_BYTES
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock

KINDS = (ArtifactKind.FLASHCARDS, ArtifactKind.QUIZ, ArtifactKind.MIND_MAP)


class SaveProgress:
    """Stores where the student stopped (known cards, answers, position)."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self, actor: Actor, notebook_id: UUID, artifact_id: UUID, state: dict[str, Any]
    ) -> None:
        """Replace the student's state (at most 16 KB).

        Raises:
            NotebookNotFoundError: Not the student's notebook or output.
            InvalidOptionsError: The output is not a deck or a quiz, or the state is
                too large.
            ArtifactNotReadyError: The output is not ready.
        """
        async with self.uow_factory() as uow:
            artifact = await load_artifact(
                uow, actor.user_id, notebook_id, artifact_id, write=False
            )
            require_ready(artifact, *KINDS)
            if content_bytes(state) > PROGRESS_MAX_BYTES:
                raise InvalidOptionsError(
                    params={
                        "details": [f"state: at most {PROGRESS_MAX_BYTES // 1024} KB"]
                    },
                    support_details="progress is too large",
                )
            await uow.progress.upsert(
                ArtifactProgress(
                    artifact_id=artifact.id,
                    user_id=actor.user_id,
                    state=state,
                    updated_at=self.clock.now(),
                )
            )
            await uow.commit()

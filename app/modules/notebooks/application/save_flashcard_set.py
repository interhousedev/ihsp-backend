"""Use case: copy a flash card output into the student's flash card sets."""

from typing import Any
from uuid import UUID

from app.modules.flashcards.domain.limits import (
    CARD_TEXT_MAX,
    MAX_CARDS_PER_SET,
    TITLE_MAX,
)
from app.modules.notebooks.application.access import load_artifact, load_notebook
from app.modules.notebooks.application.artifact_engine import require_ready
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    WorkspaceActionError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.flashcards import FlashcardsApi

DEFAULT_SET_TITLE = "Flash cards"


def card_pairs(content: dict[str, Any]) -> list[tuple[str, str]]:
    """(front, back) of the cards, trimmed to what a flash card set accepts."""
    pairs: list[tuple[str, str]] = []
    for card in content.get("cards") or []:
        front = str(card.get("front") or "").strip()[:CARD_TEXT_MAX]
        back = str(card.get("back") or "").strip()[:CARD_TEXT_MAX]
        if front and back:
            pairs.append((front, back))
    return pairs[:MAX_CARDS_PER_SET]


class SaveFlashcardSet:
    """Creates ONE flash card set per output; asking again returns the same set."""

    def __init__(
        self, *, uow_factory: UowFactory, flashcards: FlashcardsApi, clock: Clock
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.flashcards = flashcards
        self.clock = clock

    async def execute(
        self, actor: Actor, notebook_id: UUID, artifact_id: UUID
    ) -> tuple[UUID, bool]:
        """Return `(set_id, created)`; `created` is False when the set existed.

        Raises:
            NotebookNotFoundError: Not the student's notebook or output.
            InvalidOptionsError: The output is not a deck, or it has no usable card.
            ArtifactNotReadyError: The deck is not ready.
        """
        async with self.uow_factory() as uow:
            notebook = await load_notebook(uow, actor.user_id, notebook_id)
            if notebook.is_course_workspace:  # one set per output: not shareable
                raise WorkspaceActionError(params={"action": "save_flashcard_set"})
            artifact = await load_artifact(
                uow, actor.user_id, notebook_id, artifact_id, for_update=True
            )
            content = require_ready(artifact, ArtifactKind.FLASHCARDS)
            if artifact.flashcard_set_id is not None:
                return artifact.flashcard_set_id, False
            cards = card_pairs(content)
            if not cards:
                raise InvalidOptionsError(
                    params={"details": ["cards: the deck has no usable card"]},
                    support_details="no cards to save",
                )
            created = await self.flashcards.create_set(
                actor.user_id,
                artifact.title.strip()[:TITLE_MAX] or DEFAULT_SET_TITLE,
                cards,
                source="ai",
            )
            set_id = UUID(str(created["id"]))
            artifact.flashcard_set_id = set_id
            artifact.updated_at = self.clock.now()
            await uow.artifacts.save(artifact)
            await uow.commit()
        return set_id, True

"""Source kind `flashcard_set`: one of the student's flash card sets (§ 3.2.1)."""

import hashlib
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.notebooks.application.readers.base import (
    ResolvedSource,
    SourceText,
    clean_title,
    expect_input,
)
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceFailure, SourceKind
from app.modules.notebooks.domain.errors import SourceForbiddenError, SourceReadError
from app.modules.notebooks.domain.source_input import FlashcardSetInput, SourceInput
from app.shared.contracts.flashcards import FlashcardsApi

CARDS_PER_PASSAGE = 10
SEPARATOR = "\n\n"


def cards_of(flashcard_set: dict[str, Any]) -> list[dict[str, Any]]:
    """The set's cards in the order of their positions."""
    cards = list(flashcard_set.get("cards") or [])
    return sorted(cards, key=lambda card: int(card.get("position", 0)))


def cards_text(cards: Sequence[dict[str, Any]]) -> tuple[str, tuple[int, ...]]:
    """``Q: ...`` / ``A: ...`` per card; a unit starts at every tenth card."""
    parts: list[str] = []
    starts: list[int] = []
    offset = 0
    for index, card in enumerate(cards):
        part = f"Q: {str(card['front']).strip()}\nA: {str(card['back']).strip()}"
        if index % CARDS_PER_PASSAGE == 0:
            starts.append(offset)
        parts.append(part)
        offset += len(part) + len(SEPARATOR)
    return SEPARATOR.join(parts), tuple(starts)


def cards_version(cards: Sequence[dict[str, Any]]) -> str:
    """Hash of the cards' texts and order: changes when a card is added or edited."""
    digest = hashlib.sha256()
    for card in cards:
        digest.update(f"{card['front']}\x1f{card['back']}\x1e".encode())
    return digest.hexdigest()[:32]


class FlashcardReader:
    """Reads a set through `FlashcardsApi.get_set` (the owner's sets only)."""

    def __init__(self, flashcards: FlashcardsApi) -> None:
        """Store the flash cards API."""
        self.flashcards = flashcards

    async def resolve(self, user_id: UUID, source_input: SourceInput) -> ResolvedSource:
        """The set must be the user's own."""
        item = expect_input(source_input, FlashcardSetInput)
        found = await self.flashcards.get_set(item.set_id, user_id)
        if found is None:
            raise SourceForbiddenError()
        return ResolvedSource(
            kind=SourceKind.FLASHCARD_SET,
            title=clean_title(found.get("title"), "Flash cards"),
            ref={"set_id": str(item.set_id)},
            ref_key=f"fc:{item.set_id}",
        )

    async def read(self, source: Source) -> SourceText:
        """One ``Q/A`` block per card; the version is a hash of the cards."""
        found = await self._get(source)
        if found is None:
            raise SourceReadError(SourceFailure.DELETED.value)
        cards = cards_of(found)
        text, starts = cards_text(cards)
        return SourceText(
            text=text, unit_starts=starts, upstream_version=cards_version(cards)
        )

    async def current_version(self, source: Source) -> str | None:
        """The hash of the set's cards now (None when the set is gone)."""
        found = await self._get(source)
        return None if found is None else cards_version(cards_of(found))

    async def _get(self, source: Source) -> dict[str, Any] | None:
        set_id = UUID(str(source.ref["set_id"]))
        return await self.flashcards.get_set(set_id, source.owner_id)

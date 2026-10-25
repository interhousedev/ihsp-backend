"""FlashcardsApi.get_set with the shape of the flashcards module."""

from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID

from app.shared.ids import new_id


class FakeFlashcardSets:
    """Sets of several owners; ``get_set`` returns ``cards[{id, position, ...}]``."""

    def __init__(self) -> None:
        """Start without sets."""
        self.sets: dict[UUID, dict[str, Any]] = {}
        self.create_calls: list[dict[str, Any]] = []

    def add_set(
        self,
        owner_id: UUID,
        title: str = "Cell biology",
        cards: tuple[tuple[str, str], ...] = (
            ("Powerhouse of the cell", "Mitochondria"),
            ("Site of photosynthesis", "Chloroplast"),
        ),
    ) -> dict[str, Any]:
        """Store a set of (front, back) cards."""
        found: dict[str, Any] = {
            "id": new_id(),
            "owner_id": owner_id,
            "title": title,
            "description": None,
            "source": "manual",
            "cards": [],
        }
        self.sets[found["id"]] = found
        self.append(found["id"], *cards)
        return found

    def append(self, set_id: UUID, *cards: tuple[str, str]) -> None:
        """Add cards to the end of a set."""
        found = self.sets[set_id]
        for front, back in cards:
            found["cards"].append(
                {
                    "id": new_id(),
                    "position": len(found["cards"]) + 1,
                    "front": front,
                    "back": back,
                }
            )
        found["card_count"] = len(found["cards"])

    def edit(self, set_id: UUID, index: int, back: str) -> None:
        """Change the back of a card."""
        self.sets[set_id]["cards"][index]["back"] = back

    async def get_set(
        self, set_id: UUID, owner_id: UUID | None
    ) -> dict[str, Any] | None:
        """Return the set of the owner (or any set for a public read)."""
        found = self.sets.get(set_id)
        if found is None or (owner_id is not None and found["owner_id"] != owner_id):
            return None
        return found

    async def create_set(
        self,
        owner_id: UUID,
        title: str,
        cards: Sequence[tuple[str, str]],
        *,
        source: Literal["manual", "ai", "mcp", "copied"],
        source_chat_id: UUID | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a set of (front, back) cards and remember the call."""
        created = self.add_set(owner_id, title, tuple(cards))
        created["source"] = source
        self.create_calls.append({"title": title, "source": source, "cards": cards})
        return created

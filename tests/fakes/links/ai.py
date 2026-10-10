"""In-memory AiQueries and FlashcardsApi."""

from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID

from app.shared.ids import new_id


class FakeAi:
    """Chats with owner, messages and an admin flag."""

    def __init__(self) -> None:
        """Start with no chats."""
        self.chats: dict[UUID, dict[str, Any]] = {}

    def add_chat(
        self,
        owner_id: UUID,
        messages: list[tuple[str, str]],
        *,
        title: str = "Derivatives",
        admin: bool = False,
    ) -> UUID:
        """Create a chat from (role, text) pairs; seq starts at 1."""
        chat_id = new_id()
        self.chats[chat_id] = {
            "owner": owner_id,
            "title": title,
            "admin": admin,
            "messages": [
                {"seq": i, "role": role, "text": text, "tool_notes": []}
                for i, (role, text) in enumerate(messages, start=1)
            ],
        }
        return chat_id

    def append(self, chat_id: UUID, role: str, text: str) -> None:
        """Add a message to the chat."""
        messages = self.chats[chat_id]["messages"]
        messages.append(
            {"seq": len(messages) + 1, "role": role, "text": text, "tool_notes": []}
        )

    async def pending_approvals(self, user_id: UUID) -> int:
        """Return zero."""
        return 0

    async def chat_for_share(
        self, chat_id: UUID, until_seq: int | None
    ) -> dict[str, Any] | None:
        """Return the shareable chat; administration chats are never shareable."""
        chat = self.chats.get(chat_id)
        if chat is None or chat["admin"]:
            return None
        messages = [
            m for m in chat["messages"] if until_seq is None or m["seq"] <= until_seq
        ]
        return {"title": chat["title"], "owner_id": chat["owner"], "messages": messages}

    async def chat_owner(self, chat_id: UUID) -> UUID | None:
        """Return the owner of the chat."""
        chat = self.chats.get(chat_id)
        return chat["owner"] if chat else None


class FakeFlashcards:
    """Flash card sets with an owner."""

    def __init__(self) -> None:
        """Start with no sets."""
        self.sets: dict[UUID, dict[str, Any]] = {}

    def add_set(
        self, owner_id: UUID, cards: list[tuple[str, str]], *, title: str = "Verbs"
    ) -> UUID:
        """Create a set from (front, back) pairs."""
        set_id = new_id()
        self.sets[set_id] = {
            "id": str(set_id),
            "owner": owner_id,
            "title": title,
            "cards": [
                {"id": str(new_id()), "position": i, "front": f, "back": b}
                for i, (f, b) in enumerate(cards)
            ],
        }
        return set_id

    async def list_sets(self, owner_id: UUID) -> list[dict[str, Any]]:
        """Return the owner's sets."""
        return [s for s in self.sets.values() if s["owner"] == owner_id]

    async def get_set(
        self, set_id: UUID, owner_id: UUID | None
    ) -> dict[str, Any] | None:
        """Return the set (public read when owner_id is None)."""
        found = self.sets.get(set_id)
        if found is None:
            return None
        if owner_id is not None and found["owner"] != owner_id:
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
        """Create a set."""
        set_id = self.add_set(owner_id, list(cards), title=title)
        return self.sets[set_id]

    async def add_cards(
        self, owner_id: UUID, set_id: UUID, cards: Sequence[tuple[str, str]]
    ) -> dict[str, Any]:
        """Return the set unchanged."""
        return self.sets[set_id]

    async def update_card(
        self, owner_id: UUID, card_id: UUID, front: str | None, back: str | None
    ) -> dict[str, Any]:
        """Return an empty card."""
        return {}

    async def set_owner(self, set_id: UUID) -> UUID | None:
        """Return the owner of the set."""
        found = self.sets.get(set_id)
        return found["owner"] if found else None


class FakeNotebooks:
    """Ready Studio outputs with an owner."""

    def __init__(self) -> None:
        """Start with no outputs."""
        self.artifacts: dict[UUID, dict[str, Any]] = {}

    def add_artifact(
        self,
        owner_id: UUID,
        kind: str,
        content: dict[str, Any],
        *,
        title: str = "Cells",
    ) -> UUID:
        """Create a ready output."""
        artifact_id = new_id()
        self.artifacts[artifact_id] = {
            "id": str(artifact_id),
            "owner_id": owner_id,
            "kind": kind,
            "title": title,
            "options": {},
            "content": content,
        }
        return artifact_id

    async def shared_artifact(self, artifact_id: UUID) -> dict[str, Any] | None:
        """Return the output or None."""
        return self.artifacts.get(artifact_id)

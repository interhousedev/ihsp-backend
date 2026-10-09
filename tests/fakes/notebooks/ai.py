"""AiQueries.chat_transcript for the notebooks tests."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.shared.ids import new_id


@dataclass(slots=True)
class FakeChat:
    """An assistant chat; ``messages`` are ``{seq, role, text}`` (text may be empty)."""

    id: UUID
    owner_id: UUID
    title: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    admin: bool = False
    deleted: bool = False


class FakeChats:
    """Chats of several owners; ``chat_transcript`` follows the real contract."""

    def __init__(self) -> None:
        """Start without chats."""
        self.chats: dict[UUID, FakeChat] = {}
        self.calls: list[tuple[UUID, UUID, int | None]] = []

    def add_chat(
        self,
        owner_id: UUID,
        title: str = "Photosynthesis",
        turns: tuple[tuple[str, str], ...] = (
            ("What is photosynthesis?", "Plants turn light into sugar."),
            ("Where does it happen?", "In the chloroplasts of the leaf."),
        ),
        *,
        admin: bool = False,
    ) -> FakeChat:
        """A chat with the given (question, answer) turns."""
        chat = FakeChat(new_id(), owner_id, title, admin=admin)
        self.chats[chat.id] = chat
        for question, answer in turns:
            self.say(chat.id, "user", question)
            self.say(chat.id, "assistant", answer)
        return chat

    def say(self, chat_id: UUID, role: str, text: str) -> int:
        """Append a message; an empty text is a tool-only message (not in the text)."""
        chat = self.chats[chat_id]
        seq = len(chat.messages) + 1
        chat.messages.append({"seq": seq, "role": role, "text": text})
        return seq

    async def chat_transcript(
        self, owner_id: UUID, chat_id: UUID, until_seq: int | None
    ) -> dict[str, Any] | None:
        """Texts up to ``until_seq``; ``last_seq`` is the whole chat's highest seq."""
        self.calls.append((owner_id, chat_id, until_seq))
        chat = self.chats.get(chat_id)
        if chat is None or chat.deleted or chat.admin or chat.owner_id != owner_id:
            return None
        return {
            "title": chat.title,
            "last_message_at": None,
            "last_seq": len(chat.messages),
            "messages": [
                {"seq": m["seq"], "role": m["role"], "text": m["text"]}
                for m in chat.messages
                if m["text"].strip() and (until_seq is None or m["seq"] <= until_seq)
            ],
        }

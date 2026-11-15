"""Fake of McpHistoryTools: chats and notebooks by owner; anything else is not found."""

from typing import Any
from uuid import UUID

from app.interfaces.mcp.errors import McpNotFoundError
from app.shared.actor import Actor
from app.shared.ids import new_id


class FakeHistoryTools:
    """Rows are kept newest first; the cursor is the offset as a string."""

    def __init__(self) -> None:
        self.chats: dict[UUID, tuple[UUID, str, list[str]]] = {}
        self.notebooks: dict[UUID, tuple[UUID, str, list[str], list[str]]] = {}

    def add_chat(self, owner: UUID, title: str, texts: list[str]) -> UUID:
        """A chat of `owner` with these messages (alternating user and assistant)."""
        chat_id = new_id()
        self.chats[chat_id] = (owner, title, texts)
        return chat_id

    def add_notebook(
        self,
        owner: UUID,
        title: str,
        texts: list[str] | None = None,
        notes: list[str] | None = None,
    ) -> UUID:
        """A notebook of `owner` with a chat thread and notes."""
        notebook_id = new_id()
        self.notebooks[notebook_id] = (owner, title, texts or [], notes or [])
        return notebook_id

    async def list_chats(
        self, actor: Actor, *, cursor: str | None, limit: int
    ) -> dict[str, Any]:
        rows = [
            {"id": str(i), "title": title, "assistant": "student"}
            for i, (owner, title, _) in self.chats.items()
            if owner == actor.user_id
        ]
        return _slice(rows, "chats", cursor, limit)

    async def get_chat(
        self, user_id: UUID, chat_id: UUID, *, after_seq: int, limit: int
    ) -> dict[str, Any]:
        owner, title, texts = self.chats.get(chat_id, (None, "", []))
        if owner != user_id:
            raise McpNotFoundError()
        return _thread(chat_id, title, texts, after_seq, limit)

    async def list_notebooks(
        self, actor: Actor, *, cursor: str | None, limit: int
    ) -> dict[str, Any]:
        rows = [
            {"id": str(i), "title": title}
            for i, (owner, title, _, _) in self.notebooks.items()
            if owner == actor.user_id
        ]
        return _slice(rows, "notebooks", cursor, limit)

    async def get_notebook_chat(
        self, user_id: UUID, notebook_id: UUID, *, after_seq: int, limit: int
    ) -> dict[str, Any]:
        found = self.notebooks.get(notebook_id)
        if found is None or found[0] != user_id:
            raise McpNotFoundError()
        return _thread(notebook_id, found[1], found[2], after_seq, limit)

    async def get_notebook_notes(
        self, user_id: UUID, notebook_id: UUID, *, offset: int, limit: int
    ) -> dict[str, Any]:
        found = self.notebooks.get(notebook_id)
        if found is None or found[0] != user_id:
            raise McpNotFoundError()
        notes = found[3]
        page = notes[offset : offset + limit]
        return {
            "id": str(notebook_id),
            "title": found[1],
            "notes": [
                {"title": f"n{offset + i}", "text": t} for i, t in enumerate(page)
            ],
            "next_offset": offset + limit if offset + limit < len(notes) else None,
        }


def _slice(
    rows: list[dict[str, Any]], key: str, cursor: str | None, limit: int
) -> dict[str, Any]:
    start = int(cursor or 0)
    end = start + limit
    return {key: rows[start:end], "next_cursor": str(end) if end < len(rows) else None}


def _thread(
    thread_id: UUID, title: str, texts: list[str], after_seq: int, limit: int
) -> dict[str, Any]:
    page = texts[after_seq : after_seq + limit]
    reached = after_seq + len(page)
    return {
        "id": str(thread_id),
        "title": title,
        "messages": [
            {"seq": after_seq + i + 1, "role": "user", "text": t}
            for i, t in enumerate(page)
        ],
        "next_after_seq": reached if reached < len(texts) else None,
    }

"""Ports of the university chats: storage and the AI module's chats."""

import datetime as dt
from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from app.modules.admission.domain.uni_chat import CachedWeb, UniChatLink
from app.shared.actor import Actor


class UniChatRepository(Protocol):
    """Links, default prompts and the web research cache."""

    async def link(self, student_id: UUID, institution_id: UUID) -> UniChatLink | None:
        """Return the student's link to a university chat."""
        ...

    async def link_by_chat(self, chat_id: UUID) -> UniChatLink | None:
        """Return the link of an AI chat."""
        ...

    async def add(self, link: UniChatLink) -> UniChatLink:
        """Insert a link; when one exists already (a race), return that one."""
        ...

    async def relink(self, link: UniChatLink, old_chat_id: UUID) -> bool:
        """Point the link at `link.chat_id` if it still holds `old_chat_id`.

        Returns False when a concurrent open relinked it first.
        """
        ...

    async def claim_auto_run(self, link_id: UUID, now: dt.datetime) -> bool:
        """Record the one auto run atomically; True only for the first claimer."""
        ...

    async def prompt(self, student_id: UUID) -> str | None:
        """Return the student's default prompt."""
        ...

    async def set_prompt(self, student_id: UUID, text: str, now: dt.datetime) -> None:
        """Store (or with "" remove) the default prompt."""
        ...

    async def cached(self, kind: str, key: str) -> CachedWeb | None:
        """Return a cached web result."""
        ...

    async def store(
        self, kind: str, key: str, payload: dict[str, Any], now: dt.datetime
    ) -> None:
        """Insert or refresh a cached web result."""
        ...

    async def erase(self, student_id: UUID) -> None:
        """Delete the student's links and default prompt."""
        ...


class UniChats(Protocol):
    """The AI module's chats as admission uses them."""

    async def start(self, actor: Actor, title: str) -> UUID:
        """Create a smart-tier student chat with the title; return its id."""
        ...

    async def alive(self, chat_id: UUID, owner_id: UUID) -> bool:
        """Whether the chat exists, is not deleted and belongs to the owner."""
        ...

    async def discard(self, actor: Actor, chat_id: UUID) -> None:
        """Delete a chat that lost an opening race."""
        ...


class UniPageReader(Protocol):
    """Full texts of web pages (Exa contents)."""

    async def read(self, urls: Sequence[str]) -> dict[str, str]:
        """Return the text of each page that could be read, by its URL."""
        ...

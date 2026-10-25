"""Storage ports of the posts module."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.posts.domain.bot_mode import BotMode
from app.modules.posts.domain.post import Post


class PostRepository(Protocol):
    """The post tree (each call is its own transaction; the tree is small)."""

    async def list_all(self) -> list[Post]:
        """Every post."""
        ...

    async def add(self, post: Post) -> None:
        """Insert a post (SlugTakenError on a duplicate slug)."""
        ...

    async def save_many(self, posts: Sequence[Post]) -> None:
        """Update posts in one transaction (SlugTakenError on a duplicate slug)."""
        ...

    async def delete_many(self, ids: Sequence[UUID]) -> None:
        """Delete posts in one transaction."""
        ...


class BotModeRepository(Protocol):
    """The choice a Telegram user made on /start (guest or student)."""

    async def get(self, telegram_user_id: int) -> BotMode | None:
        """The stored choice, if any."""
        ...

    async def set(self, telegram_user_id: int, mode: BotMode) -> None:
        """Store or replace the choice."""
        ...


@dataclass(frozen=True, slots=True)
class GuestKnowledgeHit:
    """A knowledge entry marked accessible to guests."""

    title: str
    value: str


class GuestKnowledge(Protocol):
    """Search over knowledge entries with `accessible_to_guest` only."""

    async def search(self, query: str, *, limit: int = 5) -> list[GuestKnowledgeHit]:
        """Up to `limit` guest-accessible entries, best first."""
        ...

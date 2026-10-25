"""In-memory fakes of the posts ports, and the posts services built on them."""

from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from app.modules.posts.application.admin_posts import AdminPosts
from app.modules.posts.application.bot_posts import BotModes, BotPosts
from app.modules.posts.application.guest_assistant import GuestAssistant, GuestLimits
from app.modules.posts.domain.bot_mode import BotMode
from app.modules.posts.domain.errors import SlugTakenError
from app.modules.posts.domain.post import Post
from app.modules.posts.ports.repositories import GuestKnowledgeHit
from app.modules.posts.wiring import PostsServices
from app.settings import Settings
from app.shared.base_error import RateLimitedError
from app.shared.contracts.ai import LlmGateway
from tests.fakes.ai.llm import ScriptedLlm

DEFAULT_LIMITS = GuestLimits(per_minute=5, per_day=20, global_per_day=2000)


class InMemoryPostRepository:
    """`PostRepository` in a dict; enforces unique slugs and a single root."""

    def __init__(self) -> None:
        """Start empty."""
        self.posts: dict[UUID, Post] = {}

    async def list_all(self) -> list[Post]:
        """Every post."""
        return list(self.posts.values())

    def _check(self, posts: dict[UUID, Post]) -> None:
        slugs = [p.slug for p in posts.values()]
        if len(slugs) != len(set(slugs)):
            raise SlugTakenError()
        assert sum(p.is_root for p in posts.values()) <= 1

    async def add(self, post: Post) -> None:
        """Insert."""
        candidate = {**self.posts, post.id: post}
        self._check(candidate)
        self.posts = candidate

    async def save_many(self, posts: Sequence[Post]) -> None:
        """Update existing posts."""
        candidate = dict(self.posts)
        candidate.update({p.id: p for p in posts if p.id in self.posts})
        self._check(candidate)
        self.posts = candidate

    async def delete_many(self, ids: Sequence[UUID]) -> None:
        """Delete."""
        for post_id in ids:
            self.posts.pop(post_id, None)


class InMemoryBotModeRepository:
    """`BotModeRepository` in a dict."""

    def __init__(self) -> None:
        """Start empty."""
        self.modes: dict[int, BotMode] = {}

    async def get(self, telegram_user_id: int) -> BotMode | None:
        """The choice."""
        return self.modes.get(telegram_user_id)

    async def set(self, telegram_user_id: int, mode: BotMode) -> None:
        """Store the choice."""
        self.modes[telegram_user_id] = mode


class FakeGuestKnowledge:
    """Guest-accessible entries only; records queries."""

    def __init__(self, hits: list[GuestKnowledgeHit] | None = None) -> None:
        """Start with fixed hits."""
        self.hits = hits or []
        self.queries: list[str] = []

    async def search(self, query: str, *, limit: int = 5) -> list[GuestKnowledgeHit]:
        """Record and return the hits."""
        self.queries.append(query)
        return list(self.hits[:limit])


class FakeLimiter:
    """`RateLimiter.hit` with counters in memory."""

    def __init__(self) -> None:
        """Start with no hits."""
        self.counts: dict[str, int] = {}

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        """Count; raise over the limit."""
        self.counts[key] = self.counts.get(key, 0) + 1
        if self.counts[key] > limit:
            raise RateLimitedError(params={"retry_after": window_seconds})
        return self.counts[key]


def fake_posts_services(
    *,
    llm: Any = None,
    knowledge: FakeGuestKnowledge | None = None,
    limits: GuestLimits = DEFAULT_LIMITS,
) -> PostsServices:
    """Posts services over in-memory fakes (the repos are reachable on the result)."""
    posts = InMemoryPostRepository()
    modes = InMemoryBotModeRepository()
    settings = Settings(env="test")
    return PostsServices(
        admin=AdminPosts(posts),
        bot_posts=BotPosts(posts),
        bot_modes=BotModes(modes),
        guest_assistant=GuestAssistant(
            llm=cast(LlmGateway, llm or ScriptedLlm()),
            knowledge=knowledge or FakeGuestKnowledge(),
            limiter=FakeLimiter(),
            limits=lambda: limits,
            profile=settings.ai_profile,
        ),
    )

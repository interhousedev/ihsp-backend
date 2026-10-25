"""Builds the posts module services (container.posts)."""

from dataclasses import dataclass

from app.modules.posts.application.admin_posts import AdminPosts
from app.modules.posts.application.bot_posts import BotModes, BotPosts
from app.modules.posts.application.guest_assistant import (
    GuestAssistant,
    GuestLimits,
    HitLimiter,
)
from app.modules.posts.infrastructure.repositories import (
    SqlBotModeRepository,
    SqlPostRepository,
)
from app.modules.posts.ports.repositories import (
    BotModeRepository,
    GuestKnowledge,
    PostRepository,
)
from app.shared.contracts.ai import LlmGateway
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class PostsServices:
    """Use cases of the posts module."""

    admin: AdminPosts
    bot_posts: BotPosts
    bot_modes: BotModes
    guest_assistant: GuestAssistant


@dataclass(frozen=True, slots=True)
class PostsOverrides:
    """Replacements for infrastructure, used by tests only."""

    posts: PostRepository | None = None
    modes: BotModeRepository | None = None
    limiter: HitLimiter | None = None


def build(
    deps: ModuleDeps,
    *,
    llm: LlmGateway,
    knowledge: GuestKnowledge,
    overrides: PostsOverrides | None = None,
) -> PostsServices:
    """Wire the use cases of the posts module."""
    custom = overrides or PostsOverrides()
    posts = custom.posts or SqlPostRepository(deps.sessionmaker)
    modes = custom.modes or SqlBotModeRepository(deps.sessionmaker)
    settings = deps.settings

    def limits() -> GuestLimits:
        return GuestLimits(
            per_minute=settings.telegram.guest_messages_per_minute,
            per_day=settings.telegram.guest_daily_messages,
            global_per_day=settings.telegram.guest_global_daily_messages,
        )

    return PostsServices(
        admin=AdminPosts(posts),
        bot_posts=BotPosts(posts),
        bot_modes=BotModes(modes),
        guest_assistant=GuestAssistant(
            llm=llm,
            knowledge=knowledge,
            limiter=custom.limiter or deps.rate_limiter,
            limits=limits,
            profile=settings.ai_profile,
        ),
    )

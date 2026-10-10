"""The container: infrastructure shared by every process, plus module services."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.settings import Settings
from app.shared.clock import Clock, SystemClock
from app.shared.contracts.ai import AdminToolBackend
from app.shared.contracts.notify import TelegramSender
from app.shared.db.engine import make_engine, make_sessionmaker
from app.shared.i18n.core import I18nCore
from app.shared.paths import LOCALES_DIR
from app.shared.rate_limit import RateLimiter
from app.shared.tasks import TaskKicker

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from app.interfaces.mcp.ports import ConnectorCoursesPort, McpAuditPort
    from app.modules.academic.wiring import AcademicModule
    from app.modules.admin.wiring import AdminServices
    from app.modules.ai.wiring import AiServices
    from app.modules.dashboard.wiring import DashboardServices
    from app.modules.files.wiring import FilesServices
    from app.modules.flashcards.wiring import FlashcardsServices
    from app.modules.identity.wiring import IdentityModule
    from app.modules.library.wiring import LibraryServices
    from app.modules.links.wiring import LinksServices
    from app.modules.lms.wiring import LmsModule
    from app.modules.mail.wiring import MailServices
    from app.modules.notebooks.wiring import NotebooksServices
    from app.modules.notify.wiring import NotifyServices

# A module the current process does not build stays None (tests set what they need).
NOT_BUILT: Any = None


@dataclass(slots=True)
class Container:
    """Everything a process needs: infrastructure plus the modules it builds."""

    settings: Settings
    clock: Clock
    redis: Redis
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    kicker: TaskKicker
    rate_limiter: RateLimiter
    i18n: I18nCore
    telegram: TelegramSender = NOT_BUILT
    identity: "IdentityModule" = NOT_BUILT
    academic: "AcademicModule" = NOT_BUILT
    files: "FilesServices" = NOT_BUILT
    links: "LinksServices" = NOT_BUILT
    notify: "NotifyServices" = NOT_BUILT
    admin: "AdminServices" = NOT_BUILT
    ai: "AiServices" = NOT_BUILT
    flashcards: "FlashcardsServices" = NOT_BUILT
    dashboard: "DashboardServices" = NOT_BUILT
    mail: "MailServices" = NOT_BUILT
    lms: "LmsModule" = NOT_BUILT
    notebooks: "NotebooksServices" = NOT_BUILT
    library: "LibraryServices" = NOT_BUILT
    admin_tools: AdminToolBackend = NOT_BUILT
    mcp_audit: "McpAuditPort" = NOT_BUILT
    mcp_connector_courses: "ConnectorCoursesPort" = NOT_BUILT
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    async def close(self) -> None:
        """Close module clients (S3, EMIS, Telegram), Redis and the engine."""
        for closer in reversed(self.closers):
            await closer()
        await self.redis.aclose()
        await self.engine.dispose()


def build_infrastructure(settings: Settings, kicker: TaskKicker) -> Container:
    """Build the infrastructure part of the container (opens no connection)."""
    redis = Redis.from_url(settings.redis.url, decode_responses=True)
    engine = make_engine(settings.database.url, settings.database.pool_size)
    return Container(
        settings=settings,
        clock=SystemClock(),
        redis=redis,
        engine=engine,
        sessionmaker=make_sessionmaker(engine),
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=I18nCore(LOCALES_DIR).load(),
    )

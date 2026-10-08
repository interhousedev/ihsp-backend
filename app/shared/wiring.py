"""Infrastructure handed to every module's build() function."""

from dataclasses import dataclass

from app.settings import Settings
from app.shared.clock import Clock
from app.shared.db.uow import AfterCommit, AuditWriter, OutboxWriter
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.tasks import TaskKicker

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class ModuleDeps:
    """Infrastructure every module's build() receives."""

    settings: Settings
    clock: Clock
    redis: Redis
    sessionmaker: async_sessionmaker[AsyncSession]
    kicker: TaskKicker
    rate_limiter: RateLimiter
    i18n: I18nCore
    outbox_writer: OutboxWriter
    audit_writer: AuditWriter
    outbox_committed_hook: AfterCommit | None  # I1: kicks notify.dispatch_due

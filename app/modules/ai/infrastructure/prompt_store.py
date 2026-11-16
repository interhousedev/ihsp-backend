"""SQL side of the editable prompts: versions, their loader, transaction and stats."""

from collections.abc import Sequence
from datetime import datetime

from app.modules.ai.domain.prompt_registry import BUILT_IN_VERSION, PromptVersion
from app.modules.ai.infrastructure.orm.chat_message import ChatMessage
from app.modules.ai.infrastructure.orm.prompt_version import PromptVersionRow
from app.modules.ai.infrastructure.orm.usage_event import UsageEventRow
from app.modules.ai.ports.prompts import (
    PromptCallStats,
    PromptCallTrace,
    PromptRatingStats,
)
from app.shared.db.uow import SqlUnitOfWork

from sqlalchemy import Integer, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _entity(row: PromptVersionRow) -> PromptVersion:
    return PromptVersion(
        id=row.id,
        task=row.task,
        name=row.name,
        locale=row.locale,
        version=row.version,
        text=row.text,
        hash=row.hash,
        active=row.active,
        created_at=row.created_at,
        created_by=row.created_by,
        note=row.note,
    )


class SqlPromptVersionRepository:
    """Implements `PromptVersionRepository` on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self.session = session

    async def history(self, task: str, name: str) -> list[PromptVersion]:
        """Every version of the slot, newest first."""
        rows = await self.session.scalars(
            select(PromptVersionRow)
            .where(PromptVersionRow.task == task, PromptVersionRow.name == name)
            .order_by(PromptVersionRow.version.desc())
        )
        return [_entity(row) for row in rows]

    async def active(self, task: str | None = None) -> list[PromptVersion]:
        """The active versions (of one task)."""
        query = select(PromptVersionRow).where(PromptVersionRow.active)
        if task is not None:
            query = query.where(PromptVersionRow.task == task)
        return [_entity(row) for row in await self.session.scalars(query)]

    async def next_version(self, task: str) -> int:
        """One more than the task's highest version (numbers are per task)."""
        top = await self.session.scalar(
            select(func.max(PromptVersionRow.version)).where(
                PromptVersionRow.task == task
            )
        )
        return (top or BUILT_IN_VERSION) + 1

    async def add(self, version: PromptVersion) -> None:
        """Insert a version (inactive; `activate` turns it on)."""
        self.session.add(
            PromptVersionRow(
                id=version.id,
                task=version.task,
                name=version.name,
                locale=version.locale,
                version=version.version,
                text=version.text,
                hash=version.hash,
                active=False,
                created_by=version.created_by,
                note=version.note,
                created_at=version.created_at,
            )
        )
        await self.session.flush()

    async def activate(self, task: str, name: str, locale: str, version: int) -> bool:
        """Make the version the slot's only active one for the locale."""
        await self.deactivate(task, name, locale)
        result = await self.session.execute(
            update(PromptVersionRow)
            .where(
                PromptVersionRow.task == task,
                PromptVersionRow.name == name,
                PromptVersionRow.locale == locale,
                PromptVersionRow.version == version,
            )
            .values(active=True)
        )
        return bool(getattr(result, "rowcount", 0))

    async def deactivate(self, task: str, name: str, locale: str) -> int:
        """Turn off the slot's active version for the locale; how many changed."""
        result = await self.session.execute(
            update(PromptVersionRow)
            .where(
                PromptVersionRow.task == task,
                PromptVersionRow.name == name,
                PromptVersionRow.locale == locale,
                PromptVersionRow.active,
            )
            .values(active=False)
        )
        return int(getattr(result, "rowcount", 0) or 0)


class SqlPromptVersionLoader:
    """Implements `PromptVersionLoader`: every active version, in a short session."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self.sessionmaker = sessionmaker

    async def active(self) -> Sequence[PromptVersion]:
        """The active versions of every slot."""
        async with self.sessionmaker() as session:
            return await SqlPromptVersionRepository(session).active()


class SqlPromptUnitOfWork(SqlUnitOfWork):
    """One transaction over the prompt versions, with audit events."""

    prompts: SqlPromptVersionRepository

    def _init_repos(self) -> None:
        """Create the repository on the open session."""
        self.prompts = SqlPromptVersionRepository(self.session)


class SqlPromptAnalyticsReader:
    """Implements `PromptAnalyticsReader` over the ledger and the rated replies."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self.sessionmaker = sessionmaker

    async def calls(
        self, task: str | None, start: datetime, end: datetime
    ) -> list[PromptCallStats]:
        """The ledger's calls grouped by task and prompt version (0 built-in)."""
        event = UsageEventRow
        version = func.coalesce(event.prompt_version, BUILT_IN_VERSION)
        query = (
            select(
                event.task,
                version,
                func.count(),
                func.count().filter(event.success.is_(False)),
                func.percentile_cont(0.5).within_group(event.latency_ms),
                func.percentile_cont(0.95).within_group(event.latency_ms),
                func.coalesce(func.sum(event.input_tokens), 0),
                func.coalesce(func.sum(event.output_tokens), 0),
                func.coalesce(func.sum(event.cost_micro), 0),
            )
            .where(event.occurred_at >= start, event.occurred_at < end)
            .group_by(event.task, version)
        )
        if task is not None:
            query = query.where(event.task == task)
        async with self.sessionmaker() as session:
            rows = (await session.execute(query)).all()
        return [
            PromptCallStats(
                task=row[0],
                version=int(row[1]),
                calls=int(row[2]),
                failed=int(row[3]),
                p50_ms=float(row[4]) if row[4] is not None else None,
                p95_ms=float(row[5]) if row[5] is not None else None,
                input_tokens=int(row[6]),
                output_tokens=int(row[7]),
                cost_micro=int(row[8]),
            )
            for row in rows
        ]

    async def trace(
        self, task: str, version: int | None, limit: int
    ) -> list[PromptCallTrace]:
        """The latest ledger rows of a task, newest first."""
        event = UsageEventRow
        query = select(event).where(event.task == task)
        if version is not None:
            query = query.where(
                func.coalesce(event.prompt_version, BUILT_IN_VERSION) == version
            )
        query = query.order_by(event.occurred_at.desc()).limit(limit)
        async with self.sessionmaker() as session:
            rows = (await session.execute(query)).scalars().all()
        return [
            PromptCallTrace(
                occurred_at=row.occurred_at,
                task=row.task,
                model=row.model,
                version=row.prompt_version or BUILT_IN_VERSION,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                cost_micro=row.cost_micro,
                latency_ms=row.latency_ms,
                success=row.success,
                error=row.error,
            )
            for row in rows
        ]

    async def ratings(
        self, task: str | None, start: datetime, end: datetime
    ) -> list[PromptRatingStats]:
        """The rated assistant replies (+1/-1) grouped by task and prompt version."""
        message = ChatMessage
        version = func.coalesce(message.prompt_version, BUILT_IN_VERSION)
        query = (
            select(
                message.prompt_task,
                version,
                func.count(),
                func.avg(cast(message.feedback, Integer)),
            )
            .where(
                message.feedback.is_not(None),
                message.prompt_task.is_not(None),
                message.created_at >= start,
                message.created_at < end,
            )
            .group_by(message.prompt_task, version)
        )
        if task is not None:
            query = query.where(message.prompt_task == task)
        async with self.sessionmaker() as session:
            rows = (await session.execute(query)).all()
        return [
            PromptRatingStats(
                task=str(row[0]),
                version=int(row[1]),
                ratings=int(row[2]),
                average=float(row[3] or 0.0),
            )
            for row in rows
        ]

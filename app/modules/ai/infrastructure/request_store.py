"""SQL side of the AI request registry and the published prompt defaults."""

from collections.abc import Sequence
from datetime import datetime

from app.modules.ai.infrastructure.orm.ai_request import AiRequestRow
from app.modules.ai.infrastructure.orm.prompt_default import PromptDefaultRow
from app.modules.ai.infrastructure.prompt_store import SqlPromptVersionRepository
from app.modules.ai.ports.requests import PromptDefault, RequestRecord
from app.shared.db.uow import SqlUnitOfWork

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

PUBLISH_LOCK_KEY = "ai.publish"


def _record(row: AiRequestRow) -> RequestRecord:
    return RequestRecord(
        id=row.id,
        owner_app=row.owner_app,
        task=row.task,
        template_id=row.template_id,
        pipeline=_pipeline(row.task),
        args_schema=row.args_schema,
        tools=tuple(row.tools),
        summary=row.summary,
        published_at=row.published_at,
        retired=row.retired,
        code_version=row.code_version,
    )


def _pipeline(task: str) -> str:
    from app.shared.ai_tasks import AiTask, pipeline_of

    return str(pipeline_of(AiTask(task)))


class SqlAiRequestRepository:
    """Implements `AiRequestRepository` on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self.session = session

    async def list(
        self,
        *,
        owner_app: str | None = None,
        pipeline: str | None = None,
        include_retired: bool = False,
    ) -> list[RequestRecord]:
        """The registered requests, filtered; retired ones only when asked."""
        query = select(AiRequestRow).order_by(AiRequestRow.id)
        if not include_retired:
            query = query.where(AiRequestRow.retired.is_(False))
        if owner_app is not None:
            query = query.where(AiRequestRow.owner_app == owner_app)
        records = [_record(row) for row in await self.session.scalars(query)]
        if pipeline is not None:
            records = [r for r in records if r.pipeline == pipeline]
        return records

    async def get(self, request_id: str) -> RequestRecord | None:
        """One registered request, or None."""
        row = await self.session.get(AiRequestRow, request_id)
        return None if row is None else _record(row)

    async def upsert(self, record: RequestRecord) -> None:
        """Insert or replace a request by id."""
        row = await self.session.get(AiRequestRow, record.id)
        values = {
            "owner_app": record.owner_app,
            "task": record.task,
            "template_id": record.template_id,
            "args_schema": dict(record.args_schema),
            "tools": list(record.tools),
            "summary": record.summary,
            "published_at": record.published_at,
            "retired": record.retired,
            "code_version": record.code_version,
        }
        if row is None:
            self.session.add(AiRequestRow(id=record.id, **values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await self.session.flush()

    async def retire_except(self, request_ids: set[str]) -> int:
        """Retire the requests not listed; how many changed."""
        result = await self.session.execute(
            update(AiRequestRow)
            .where(
                AiRequestRow.id.not_in(sorted(request_ids)),
                AiRequestRow.retired.is_(False),
            )
            .values(retired=True)
        )
        return int(getattr(result, "rowcount", 0) or 0)


class SqlPromptDefaultRepository:
    """Implements `PromptDefaultRepository` on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self.session = session

    async def get(self, task: str, name: str) -> PromptDefault | None:
        """The stored default of the slot, or None."""
        row = await self.session.get(PromptDefaultRow, (task, name))
        if row is None:
            return None
        return PromptDefault(row.task, row.name, row.version, row.hash, row.text)

    async def upsert(self, default: PromptDefault, updated_at: datetime) -> None:
        """Insert or replace the default of the slot."""
        row = await self.session.get(PromptDefaultRow, (default.task, default.name))
        if row is None:
            self.session.add(
                PromptDefaultRow(
                    task=default.task,
                    name=default.name,
                    version=default.version,
                    hash=default.hash,
                    text=default.text,
                    updated_at=updated_at,
                )
            )
        else:
            row.version = default.version
            row.hash = default.hash
            row.text = default.text
            row.updated_at = updated_at
        await self.session.flush()


class SqlRequestPublishUnitOfWork(SqlUnitOfWork):
    """One transaction for publishing: prompt versions, defaults and the registry."""

    prompts: SqlPromptVersionRepository
    defaults: SqlPromptDefaultRepository
    requests: SqlAiRequestRepository

    async def try_lock(self) -> bool:
        """Take the transaction-scoped advisory lock of the publish, if free."""
        taken = await self.session.scalar(
            text("select pg_try_advisory_xact_lock(hashtext(:key))"),
            {"key": PUBLISH_LOCK_KEY},
        )
        return bool(taken)

    def _init_repos(self) -> None:
        """Create the repositories on the open session."""
        self.prompts = SqlPromptVersionRepository(self.session)
        self.defaults = SqlPromptDefaultRepository(self.session)
        self.requests = SqlAiRequestRepository(self.session)


__all__: Sequence[str] = [
    "SqlAiRequestRepository",
    "SqlPromptDefaultRepository",
    "SqlRequestPublishUnitOfWork",
]

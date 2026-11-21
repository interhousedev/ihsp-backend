"""SQL side of the connectors and pipeline routes: repositories, loader, transaction."""

from uuid import UUID

from app.modules.ai.domain.connectors import (
    BUILTIN_IDS,
    Connector,
    ConnectorKind,
    Pipeline,
    PipelineRoute,
    TracingConfig,
)
from app.modules.ai.infrastructure.orm.connector import ConnectorRow
from app.modules.ai.infrastructure.orm.pipeline_route import PipelineRouteRow
from app.modules.ai.infrastructure.orm.tracing_settings import TracingSettingsRow
from app.modules.ai.ports.connectors import RoutingSnapshot
from app.shared.db.uow import SqlUnitOfWork

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _connector(row: ConnectorRow) -> Connector:
    return Connector(
        id=row.id,
        kind=ConnectorKind(row.kind),
        title=row.title,
        base_url=row.base_url,
        enabled=row.enabled,
        has_secret=row.has_secret,
        secret_last4=row.secret_last4,
        builtin=row.id in BUILTIN_IDS,
        source="db",
    )


def _route(row: PipelineRouteRow) -> PipelineRoute | None:
    try:
        pipeline = Pipeline(row.pipeline)
    except ValueError:  # a pipeline the code no longer has
        return None
    return PipelineRoute(
        pipeline=pipeline,
        connector_id=row.connector_id,
        model=row.model,
        reasoning_effort=row.reasoning_effort,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
        tracing_enabled=row.tracing_enabled,
        capture_content=row.capture_content,
    )


class SqlConnectorRepository:
    """Implements `ConnectorRepository` on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self.session = session

    async def list(self) -> list[Connector]:
        """Every row, by id."""
        rows = await self.session.scalars(
            select(ConnectorRow).order_by(ConnectorRow.id)
        )
        return [_connector(row) for row in rows]

    async def get(self, id: str) -> Connector | None:
        """One row, or None."""
        row = await self.session.get(ConnectorRow, id)
        return None if row is None else _connector(row)

    async def add(self, connector: Connector, actor_id: UUID) -> None:
        """Insert a row."""
        self.session.add(
            ConnectorRow(
                id=connector.id,
                kind=connector.kind.value,
                title=connector.title,
                base_url=connector.base_url,
                enabled=connector.enabled,
                has_secret=connector.has_secret,
                secret_last4=connector.secret_last4,
                created_by=actor_id,
            )
        )
        await self.session.flush()

    async def update(self, connector: Connector) -> None:
        """Replace the row's fields."""
        row = await self.session.get(ConnectorRow, connector.id)
        if row is None:
            return
        row.title = connector.title
        row.base_url = connector.base_url
        row.enabled = connector.enabled
        row.has_secret = connector.has_secret
        row.secret_last4 = connector.secret_last4
        await self.session.flush()

    async def delete(self, id: str) -> None:
        """Delete the row."""
        await self.session.execute(delete(ConnectorRow).where(ConnectorRow.id == id))


class SqlPipelineRouteRepository:
    """Implements `PipelineRouteRepository` on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self.session = session

    async def list(self) -> list[PipelineRoute]:
        """Every route."""
        rows = await self.session.scalars(select(PipelineRouteRow))
        return [r for r in map(_route, rows) if r is not None]

    async def put(self, route: PipelineRoute) -> None:
        """Insert or replace the pipeline's route."""
        values = {
            "connector_id": route.connector_id,
            "model": route.model,
            "reasoning_effort": route.reasoning_effort,
            "updated_by": route.updated_by,
            "tracing_enabled": route.tracing_enabled,
            "capture_content": route.capture_content,
        }
        await self.session.execute(
            insert(PipelineRouteRow)
            .values(pipeline=route.pipeline.value, **values)
            .on_conflict_do_update(
                index_elements=[PipelineRouteRow.pipeline],
                set_={**values, "updated_at": route.updated_at},
            )
        )

    async def delete(self, pipeline: Pipeline) -> None:
        """Remove the pipeline's route."""
        await self.session.execute(
            delete(PipelineRouteRow).where(PipelineRouteRow.pipeline == pipeline.value)
        )


class SqlTracingSettingsRepository:
    """Implements `TracingSettingsRepository` on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self.session = session

    async def get(self) -> TracingConfig | None:
        """The row, or None."""
        row = await self.session.get(TracingSettingsRow, 1)
        if row is None:
            return None
        return TracingConfig(
            host=row.host,
            public_key=row.public_key,
            has_secret=row.has_secret,
            secret_last4=row.secret_last4,
            updated_at=row.updated_at,
            updated_by=row.updated_by,
        )

    async def put(self, config: TracingConfig) -> None:
        """Insert or replace the row."""
        values = {
            "host": config.host,
            "public_key": config.public_key,
            "has_secret": config.has_secret,
            "secret_last4": config.secret_last4,
            "updated_by": config.updated_by,
        }
        await self.session.execute(
            insert(TracingSettingsRow)
            .values(id=1, **values)
            .on_conflict_do_update(
                index_elements=[TracingSettingsRow.id],
                set_={**values, "updated_at": config.updated_at},
            )
        )

    async def delete(self) -> None:
        """Remove the row."""
        await self.session.execute(delete(TracingSettingsRow))


class SqlConnectorUnitOfWork(SqlUnitOfWork):
    """One transaction over connectors, routes and tracing, with audit events."""

    connectors: SqlConnectorRepository
    routes: SqlPipelineRouteRepository
    tracing: SqlTracingSettingsRepository

    def _init_repos(self) -> None:
        """Create the repositories on the open session."""
        self.connectors = SqlConnectorRepository(self.session)
        self.routes = SqlPipelineRouteRepository(self.session)
        self.tracing = SqlTracingSettingsRepository(self.session)


class SqlRoutingLoader:
    """Implements `RoutingLoader`: one read of both tables."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self.sessionmaker = sessionmaker

    async def load(self) -> RoutingSnapshot:
        """Every connector row and route."""
        async with self.sessionmaker() as session:
            connectors = await SqlConnectorRepository(session).list()
            routes = await SqlPipelineRouteRepository(session).list()
            tracing = await SqlTracingSettingsRepository(session).get()
        return RoutingSnapshot(
            connectors={c.id: c for c in connectors},
            routes={r.pipeline: r for r in routes},
            tracing=tracing,
        )

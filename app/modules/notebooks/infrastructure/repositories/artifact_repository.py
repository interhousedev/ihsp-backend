"""SQL repository of Studio outputs."""

from datetime import datetime
from uuid import UUID

from app.modules.notebooks.domain.entities import Artifact, ArtifactError
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.infrastructure.orm.artifact import Artifact as ArtifactRow

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.orm.attributes import flag_modified


def _to_entity(row: ArtifactRow, *, with_content: bool = True) -> Artifact:
    return Artifact(
        id=row.id,
        notebook_id=row.notebook_id,
        owner_id=row.owner_id,
        requested_by=row.requested_by,
        kind=ArtifactKind(row.kind),
        title=row.title,
        created_at=row.created_at,
        updated_at=row.updated_at,
        status=ArtifactStatus(row.status),
        format=row.format,
        error=ArtifactError.model_validate(row.error) if row.error else None,
        options=dict(row.options or {}),
        prompt=row.prompt,
        source_ids=list(row.source_ids or []),
        source_map={str(k): str(v) for k, v in (row.source_map or {}).items()},
        sampled=row.sampled,
        content=row.content if with_content else None,
        refs_index=row.refs_index,
        model=row.model,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        tokens_cached=row.tokens_cached,
        weighted=row.weighted,
        cost_micro=row.cost_micro,
        attempts=int(row.attempts),
        progress=row.progress,
        parent_id=row.parent_id,
        flashcard_set_id=row.flashcard_set_id,
        cache_key=row.cache_key,
        from_cache=row.from_cache,
        started_at=row.started_at,
        finished_at=row.finished_at,
        viewed_at=row.viewed_at,
        deleted_at=row.deleted_at,
    )


def _apply(row: ArtifactRow, artifact: Artifact) -> None:
    row.notebook_id = artifact.notebook_id
    row.owner_id = artifact.owner_id
    row.requested_by = artifact.requested_by
    row.kind = artifact.kind.value
    row.format = artifact.format
    row.title = artifact.title
    row.status = artifact.status.value
    row.error = artifact.error.model_dump(mode="json") if artifact.error else None
    row.options = artifact.options
    row.prompt = artifact.prompt
    row.source_ids = list(artifact.source_ids)
    row.source_map = artifact.source_map
    row.sampled = artifact.sampled
    row.content = artifact.content
    row.refs_index = artifact.refs_index
    row.model = artifact.model
    row.tokens_in = artifact.tokens_in
    row.tokens_out = artifact.tokens_out
    row.tokens_cached = artifact.tokens_cached
    row.weighted = artifact.weighted
    row.cost_micro = artifact.cost_micro
    row.attempts = artifact.attempts
    row.progress = artifact.progress
    row.parent_id = artifact.parent_id
    row.flashcard_set_id = artifact.flashcard_set_id
    row.cache_key = artifact.cache_key
    row.from_cache = artifact.from_cache
    row.started_at = artifact.started_at
    row.finished_at = artifact.finished_at
    row.viewed_at = artifact.viewed_at
    row.deleted_at = artifact.deleted_at
    row.created_at = artifact.created_at
    row.updated_at = artifact.updated_at


class SqlArtifactRepository:
    """Outputs in `notebooks.artifacts`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def _load(
        self, stmt: Select[tuple[ArtifactRow]], *, with_content: bool = True
    ) -> list[Artifact]:
        """Run a query and convert the rows (refreshing rows the session holds)."""
        stmt = stmt.execution_options(populate_existing=True)
        if not with_content:
            stmt = stmt.options(defer(ArtifactRow.content, raiseload=True))
        rows = (await self.session.execute(stmt)).scalars()
        return [_to_entity(row, with_content=with_content) for row in rows]

    async def add(self, artifact: Artifact) -> None:
        """Insert a new output."""
        row = ArtifactRow(id=artifact.id)
        _apply(row, artifact)
        self.session.add(row)
        await self.session.flush()

    async def get(self, artifact_id: UUID) -> Artifact | None:
        """Return the output (soft-deleted ones too)."""
        found = await self._load(
            select(ArtifactRow).where(ArtifactRow.id == artifact_id)
        )
        return found[0] if found else None

    async def get_for_update(self, artifact_id: UUID) -> Artifact | None:
        """Return the output and lock its row until the transaction ends."""
        stmt = (
            select(ArtifactRow).where(ArtifactRow.id == artifact_id).with_for_update()
        )
        found = await self._load(stmt)
        return found[0] if found else None

    async def save(self, artifact: Artifact) -> None:
        """Write the output's stored fields, `updated_at` exactly as given."""
        stmt = select(ArtifactRow).where(ArtifactRow.id == artifact.id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return
        _apply(row, artifact)
        flag_modified(row, "updated_at")
        await self.session.flush()

    async def list_for_notebook(
        self,
        notebook_id: UUID,
        *,
        kind: ArtifactKind | None,
        status: ArtifactStatus | None,
    ) -> list[Artifact]:
        """Non-deleted outputs, newest first, without content (`content` is None)."""
        stmt = select(ArtifactRow).where(
            ArtifactRow.notebook_id == notebook_id, ArtifactRow.deleted_at.is_(None)
        )
        if kind is not None:
            stmt = stmt.where(ArtifactRow.kind == kind.value)
        if status is not None:
            stmt = stmt.where(ArtifactRow.status == status.value)
        stmt = stmt.order_by(ArtifactRow.created_at.desc(), ArtifactRow.id.desc())
        return await self._load(stmt, with_content=False)

    async def count_live(self, notebook_id: UUID) -> int:
        """How many non-deleted outputs the notebook holds."""
        stmt = select(func.count(ArtifactRow.id)).where(
            ArtifactRow.notebook_id == notebook_id, ArtifactRow.deleted_at.is_(None)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def stuck_generating(
        self, started_before: datetime, limit: int
    ) -> list[Artifact]:
        """Outputs in `generating` that started before the cutoff (oldest first)."""
        stmt = (
            select(ArtifactRow)
            .where(
                ArtifactRow.status == ArtifactStatus.GENERATING.value,
                ArtifactRow.started_at < started_before,
            )
            .order_by(ArtifactRow.started_at, ArtifactRow.id)
            .limit(limit)
        )
        return await self._load(stmt)

    async def stuck_queued(
        self, updated_before: datetime, limit: int
    ) -> list[Artifact]:
        """Outputs still `queued` not updated since the cutoff (oldest first)."""
        stmt = (
            select(ArtifactRow)
            .where(
                ArtifactRow.status == ArtifactStatus.QUEUED.value,
                ArtifactRow.deleted_at.is_(None),
                ArtifactRow.updated_at < updated_before,
            )
            .order_by(ArtifactRow.updated_at, ArtifactRow.id)
            .limit(limit)
        )
        return await self._load(stmt)

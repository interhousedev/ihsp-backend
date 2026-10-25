"""SQL repository of the shared summary and Studio output caches."""

from datetime import datetime
from typing import Any, cast

from app.modules.notebooks.domain.entities import (
    CachedArtifact,
    CachedSummary,
    NotebookSummary,
)
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.infrastructure.orm.shared_cache import (
    SharedArtifact as ArtifactRow,
)
from app.modules.notebooks.infrastructure.orm.shared_cache import (
    SharedSummary as SummaryRow,
)

from sqlalchemy import CursorResult, and_, delete, or_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


class SqlSharedCacheRepository:
    """Cached summaries and Studio outputs."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def get_summary(
        self, selection_hash: str, language: str, now: datetime
    ) -> CachedSummary | None:
        """The summary kept for a set of texts; counts as a hit at `now`."""
        stmt = (
            update(SummaryRow)
            .where(
                SummaryRow.selection_hash == selection_hash,
                SummaryRow.language == language,
            )
            .values(hits=SummaryRow.hits + 1, last_hit_at=now)
            .returning(SummaryRow.summary)
        )
        raw = (await self.session.execute(stmt)).scalar_one_or_none()
        if raw is None:
            return None
        return CachedSummary(
            title=str(raw["title"]),
            emoji=raw.get("emoji"),
            summary=NotebookSummary.model_validate(raw["summary"]),
        )

    async def save_summary(
        self, selection_hash: str, language: str, summary: CachedSummary
    ) -> None:
        """Keep the summary (the first one stored for the key wins)."""
        stmt = (
            pg_insert(SummaryRow)
            .values(
                selection_hash=selection_hash,
                language=language,
                summary={
                    "title": summary.title,
                    "emoji": summary.emoji,
                    "summary": summary.summary.model_dump(mode="json"),
                },
            )
            .on_conflict_do_nothing()
        )
        await self.session.execute(stmt)

    async def get_artifact(
        self, cache_key: str, now: datetime
    ) -> CachedArtifact | None:
        """The output kept for a request; counts as a hit at `now`."""
        stmt = (
            update(ArtifactRow)
            .where(ArtifactRow.cache_key == cache_key)
            .values(hits=ArtifactRow.hits + 1, last_hit_at=now)
            .returning(ArtifactRow)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return CachedArtifact(
            cache_key=row.cache_key.strip(),
            kind=ArtifactKind(row.kind),
            title=row.title,
            format=row.format,
            content=dict(row.content),
            refs_index=None if row.refs_index is None else dict(row.refs_index),
            source_map={k: str(v) for k, v in row.source_map.items()},
            source_documents={k: str(v) for k, v in row.source_documents.items()},
            options=dict(row.options),
            sampled=bool(row.sampled),
            model=row.model,
        )

    async def save_artifact(self, entry: CachedArtifact) -> None:
        """Keep the output (the first one stored for the key wins)."""
        stmt = (
            pg_insert(ArtifactRow)
            .values(
                cache_key=entry.cache_key,
                kind=entry.kind.value,
                title=entry.title,
                format=entry.format,
                content=entry.content,
                refs_index=entry.refs_index,
                source_map=entry.source_map,
                source_documents=entry.source_documents,
                options=entry.options,
                sampled=entry.sampled,
                model=entry.model,
            )
            .on_conflict_do_nothing()
        )
        await self.session.execute(stmt)

    async def delete_stale(self, unused_since: datetime) -> int:
        """Delete cache rows created and last hit before the cutoff."""
        total = 0
        for table in (SummaryRow, ArtifactRow):
            stale = and_(
                table.created_at < unused_since,
                or_(table.last_hit_at.is_(None), table.last_hit_at < unused_since),
            )
            result = await self.session.execute(
                delete(table).where(stale),
                execution_options={"synchronize_session": False},
            )
            total += int(cast("CursorResult[Any]", result).rowcount)
        return total

"""SQL ranking of passages across notebooks (the user's own and shared kinds)."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.infrastructure.lexical_query import build_lexical_query
from app.modules.notebooks.infrastructure.orm.notebook import Notebook as NotebookRow
from app.modules.notebooks.infrastructure.orm.passage import Passage as PassageRow
from app.modules.notebooks.infrastructure.orm.source import Source as SourceRow
from app.modules.notebooks.ports.shared_passages import SharedCandidate
from app.shared.contracts.embeddings import QueryVector
from app.shared.db.embeddings import EMBEDDING_DIMS
from app.shared.db.embeddings import Embedding as EmbeddingRow
from app.shared.db.halfvec import HalfVec
from app.shared.rank_fusion import CANDIDATES, reciprocal_rank_fusion

from sqlalchemy import Float, Select, and_, func, literal, literal_column, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

SHARED_KINDS = (SourceKind.LIBRARY_ITEM.value, SourceKind.LESSON_RESOURCE.value)
USABLE = ("ready", "stale")
_COLUMNS = (
    PassageRow.id.label("passage_id"),
    SourceRow.id.label("source_id"),
    SourceRow.notebook_id,
    NotebookRow.owner_id,
    SourceRow.kind,
    SourceRow.ref,
    SourceRow.title.label("source_title"),
    PassageRow.text,
    PassageRow.seq,
)


class SqlSharedPassageReader:
    """Reads on its own short session; writes nothing."""

    def __init__(self, sessionmaker: async_sessionmaker[Any]) -> None:
        """Keep the session factory."""
        self.sessionmaker = sessionmaker

    def _scoped(self, user_id: UUID) -> Select[Any]:
        """Passages of usable sources the user owns, or of shared kinds."""
        return (
            select(*_COLUMNS)
            .select_from(PassageRow)
            .join(SourceRow, SourceRow.document_id == PassageRow.document_id)
            .join(NotebookRow, NotebookRow.id == SourceRow.notebook_id)
            .where(
                NotebookRow.deleted_at.is_(None),
                SourceRow.status.in_(USABLE),
                or_(NotebookRow.owner_id == user_id, SourceRow.kind.in_(SHARED_KINDS)),
            )
        )

    async def search(
        self, user_id: UUID, query: str, query_vector: QueryVector | None, limit: int
    ) -> list[SharedCandidate]:
        """Lexical alone, or fused with the cosine ranking by RRF."""
        if limit <= 0:
            return []
        size = max(CANDIDATES, limit)
        async with self.sessionmaker() as session:
            words = await self._lexical(session, user_id, query, size)
            meaning = (
                await self._semantic(session, user_id, query_vector, size)
                if query_vector is not None
                else []
            )
        if not meaning:
            return [_candidate(r) for r in words[:limit]]
        rows = {_key(r): r for r in (*meaning, *words)}
        order = reciprocal_rank_fusion(
            [[_key(r) for r in meaning], [_key(r) for r in words]]
        )
        return [_candidate(rows[k]) for k in order[:limit]]

    async def _lexical(
        self, session: Any, user_id: UUID, query: str, limit: int
    ) -> list[Any]:
        lexical = build_lexical_query(query)
        if lexical is None:
            return []
        tsquery = (
            func.to_tsquery(literal_column("'russian'"), lexical.russian).op("||")(
                func.to_tsquery(literal_column("'simple'"), lexical.simple)
            )
        ).label("tsq")
        wanted = select(tsquery).cte("wanted")
        rank = func.ts_rank_cd(PassageRow.search_vector, wanted.c.tsq).label("rank")
        stmt = (
            self._scoped(user_id)
            .add_columns(rank)
            .join(wanted, literal_column("true"))
            .where(PassageRow.search_vector.bool_op("@@")(wanted.c.tsq))
            .order_by(rank.desc(), SourceRow.id, PassageRow.seq)
            .limit(limit)
        )
        return list((await session.execute(stmt)).all())

    async def _semantic(
        self, session: Any, user_id: UUID, query_vector: QueryVector, limit: int
    ) -> list[Any]:
        if len(query_vector.values) != EMBEDDING_DIMS:
            return []
        point = literal(list(query_vector.values), HalfVec(EMBEDDING_DIMS))
        near = EmbeddingRow.embedding.op("<=>", return_type=Float)(point)
        stmt = (
            self._scoped(user_id)
            .add_columns(near.label("distance"))
            .join(
                EmbeddingRow,
                and_(
                    EmbeddingRow.content_hash == PassageRow.content_hash,
                    EmbeddingRow.model == query_vector.model,
                ),
            )
            .order_by(near, SourceRow.id, PassageRow.seq)
            .limit(limit)
        )
        return list((await session.execute(stmt)).all())


def _key(row: Any) -> tuple[UUID, UUID]:
    return row.source_id, row.passage_id


def _candidate(row: Any) -> SharedCandidate:
    return SharedCandidate(
        passage_id=row.passage_id,
        source_id=row.source_id,
        notebook_id=row.notebook_id,
        owner_id=row.owner_id,
        kind=str(row.kind),
        ref=dict(row.ref or {}),
        source_title=row.source_title,
        text=row.text,
    )

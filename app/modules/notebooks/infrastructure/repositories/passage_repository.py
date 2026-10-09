"""SQL repository of passages and their lexical search.

Passages belong to a document; a source reaches them through `sources.document_id`.
Every passage handed out carries the id and notebook of the source it was asked
through, so callers keep thinking in sources.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.entities import Passage
from app.modules.notebooks.infrastructure.lexical_query import build_lexical_query
from app.modules.notebooks.infrastructure.orm.passage import Passage as PassageRow
from app.modules.notebooks.infrastructure.orm.source import Source as SourceRow
from app.shared.contracts.embeddings import QueryVector, TextToEmbed
from app.shared.db.embeddings import EMBEDDING_DIMS
from app.shared.db.embeddings import Embedding as EmbeddingRow
from app.shared.db.halfvec import HalfVec
from app.shared.rank_fusion import CANDIDATES, reciprocal_rank_fusion

from sqlalchemy import (
    ARRAY,
    Float,
    Row,
    Select,
    Uuid,
    and_,
    exists,
    func,
    literal,
    literal_column,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

# Everything but the generated `search_vector`, which only the search reads.
_COLUMNS = (
    PassageRow.id,
    SourceRow.id.label("source_id"),
    SourceRow.notebook_id.label("notebook_id"),
    PassageRow.seq,
    PassageRow.text,
    PassageRow.char_start,
    PassageRow.char_end,
    PassageRow.token_estimate,
    PassageRow.page,
    PassageRow.heading,
    PassageRow.content_hash,
)


def _to_entity(row: Row[Any]) -> Passage:
    return Passage(
        id=row.id,
        source_id=row.source_id,
        notebook_id=row.notebook_id,
        seq=int(row.seq),
        text=row.text,
        char_start=int(row.char_start),
        char_end=int(row.char_end),
        token_estimate=int(row.token_estimate),
        page=row.page,
        heading=row.heading,
        content_hash=row.content_hash.strip(),
    )


def _select_passages() -> Select[Any]:
    """Passages joined to the sources that hold their document."""
    return (
        select(*_COLUMNS)
        .select_from(PassageRow)
        .join(SourceRow, SourceRow.document_id == PassageRow.document_id)
    )


class SqlPassageRepository:
    """Reads the passages of the shared documents through the sources."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def _load(self, stmt: Select[Any]) -> list[Passage]:
        return [_to_entity(row) for row in (await self.session.execute(stmt)).all()]

    async def get(self, passage_id: UUID, notebook_id: UUID) -> Passage | None:
        """One passage of the notebook (through its first source with the text)."""
        stmt = (
            _select_passages()
            .where(PassageRow.id == passage_id, SourceRow.notebook_id == notebook_id)
            .order_by(SourceRow.position, SourceRow.id)
            .limit(1)
        )
        found = await self._load(stmt)
        return found[0] if found else None

    async def get_many(
        self, passage_ids: Sequence[UUID], notebook_id: UUID
    ) -> list[Passage]:
        """The notebook's passages among the ids (any order).

        A passage whose text the notebook holds in two sources appears once per source.
        """
        if not passage_ids:
            return []
        stmt = _select_passages().where(
            PassageRow.id.in_(passage_ids), SourceRow.notebook_id == notebook_id
        )
        return await self._load(stmt)

    async def list_for_source(
        self, source_id: UUID, *, after_seq: int, limit: int
    ) -> list[Passage]:
        """Passages with `seq > after_seq`, ascending."""
        stmt = (
            _select_passages()
            .where(SourceRow.id == source_id, PassageRow.seq > after_seq)
            .order_by(PassageRow.seq)
            .limit(limit)
        )
        return await self._load(stmt)

    async def list_for_sources(self, source_ids: Sequence[UUID]) -> list[Passage]:
        """All passages of the sources, ordered by the given source order then `seq`."""
        if not source_ids:
            return []
        order = func.array_position(
            literal(list(source_ids), ARRAY(Uuid)), SourceRow.id
        )
        stmt = (
            _select_passages()
            .where(SourceRow.id.in_(source_ids))
            .order_by(order, PassageRow.seq)
        )
        return await self._load(stmt)

    async def neighbours(
        self, source_id: UUID, seq: int, context: int
    ) -> tuple[list[Passage], list[Passage]]:
        """Passages `seq-context..seq-1` and `seq+1..seq+context` (ascending)."""
        if context <= 0:
            return [], []
        stmt = (
            _select_passages()
            .where(
                SourceRow.id == source_id,
                PassageRow.seq >= seq - context,
                PassageRow.seq <= seq + context,
                PassageRow.seq != seq,
            )
            .order_by(PassageRow.seq)
        )
        found = await self._load(stmt)
        return (
            [p for p in found if p.seq < seq],
            [p for p in found if p.seq > seq],
        )

    async def search(
        self,
        notebook_id: UUID,
        source_ids: Sequence[UUID],
        query: str,
        limit: int,
        *,
        query_vector: QueryVector | None = None,
    ) -> list[Passage]:
        """Rank the passages of the sources for a question, best first.

        Without `query_vector` this is the lexical search alone (`_lexical`). With
        one, the lexical and the cosine rankings (`CANDIDATES` passages or more) are
        fused by reciprocal rank fusion. No stored vector for the notebook's passages
        means the cosine ranking is empty and the lexical result comes back as it is.
        """
        if not source_ids or limit <= 0:
            return []
        if query_vector is None:
            return await self._lexical(notebook_id, source_ids, query, limit)
        size = max(CANDIDATES, limit)
        by_words = await self._lexical(notebook_id, source_ids, query, size)
        by_meaning = await self._semantic(notebook_id, source_ids, query_vector, size)
        if not by_meaning:
            return by_words[:limit]
        found = {_hit_key(p): p for p in (*by_meaning, *by_words)}
        # Meaning first: it wins ties, because a question in another language or
        # script gives weak word matches (see docs/reference/vector-search.md).
        order = reciprocal_rank_fusion(
            [[_hit_key(p) for p in by_meaning], [_hit_key(p) for p in by_words]]
        )
        return [found[key] for key in order[:limit]]

    async def _lexical(
        self, notebook_id: UUID, source_ids: Sequence[UUID], query: str, limit: int
    ) -> list[Passage]:
        """Rank the passages of the sources for a question by its words.

        One statement over the precomputed `search_vector` (`russian` || `simple`):
        the `russian` query stems ("фотосинтезе" finds "фотосинтез"), the `simple`
        query adds prefix terms so that Uzbek endings match in both directions
        ("fotosintezda" finds "fotosintez", "fotosintez" finds "fotosintezlarning").
        Ranked by `ts_rank_cd`, then `(source_id, seq)`.

        `word_similarity` (pg_trgm) is not evaluated on every passage: on this stack
        it costs about 0.3 ms per passage and term, i.e. seconds for a notebook of
        5 000 passages, against the 150 ms budget of a chat turn.
        """
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
            select(*_COLUMNS, rank)
            .select_from(PassageRow)
            .join(SourceRow, SourceRow.document_id == PassageRow.document_id)
            .join(wanted, literal_column("true"))
            .where(
                SourceRow.notebook_id == notebook_id,
                SourceRow.id.in_(source_ids),
                PassageRow.search_vector.bool_op("@@")(wanted.c.tsq),
            )
            .order_by(rank.desc(), SourceRow.id, PassageRow.seq)
            .limit(limit)
        )
        return await self._load(stmt)

    async def _semantic(
        self,
        notebook_id: UUID,
        source_ids: Sequence[UUID],
        query_vector: QueryVector,
        limit: int,
    ) -> list[Passage]:
        """Rank the passages that have a vector of the query's model by cosine.

        The distance is computed exactly for the notebook's own passages (at most a
        few thousand), which is faster and more accurate than walking the global HNSW
        index with a notebook filter. Ties break on `(source_id, seq)`.
        """
        if len(query_vector.values) != EMBEDDING_DIMS:
            return []
        point = literal(list(query_vector.values), HalfVec(EMBEDDING_DIMS))
        distance = EmbeddingRow.embedding.op("<=>", return_type=Float)(point)
        near = distance.label("distance")
        stmt = (
            select(*_COLUMNS, near)
            .select_from(PassageRow)
            .join(SourceRow, SourceRow.document_id == PassageRow.document_id)
            .join(
                EmbeddingRow,
                and_(
                    EmbeddingRow.content_hash == PassageRow.content_hash,
                    EmbeddingRow.model == query_vector.model,
                ),
            )
            .where(SourceRow.notebook_id == notebook_id, SourceRow.id.in_(source_ids))
            .order_by(near, SourceRow.id, PassageRow.seq)
            .limit(limit)
        )
        return await self._load(stmt)

    async def missing_embeddings(
        self, model: str, limit: int, *, document_id: UUID | None = None
    ) -> list[TextToEmbed]:
        """Distinct passage texts without a vector of `model`, by content hash."""
        has_vector = exists().where(
            EmbeddingRow.content_hash == PassageRow.content_hash,
            EmbeddingRow.model == model,
        )
        stmt = (
            select(PassageRow.content_hash, PassageRow.text)
            .where(~has_vector)
            .distinct(PassageRow.content_hash)
            .order_by(PassageRow.content_hash)
            .limit(limit)
        )
        if document_id is not None:
            stmt = stmt.where(PassageRow.document_id == document_id)
        rows = (await self.session.execute(stmt)).all()
        return [TextToEmbed(row.content_hash.strip(), row.text) for row in rows]


def _hit_key(passage: Passage) -> tuple[UUID, UUID]:
    """A passage as the notebook sees it: one text held by two sources counts twice."""
    return passage.source_id, passage.id

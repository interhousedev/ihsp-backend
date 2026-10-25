"""SQL repository of knowledge entries, with trigram, full-text and vector search."""

import re
from collections.abc import Sequence
from uuid import UUID

from app.modules.knowledge.domain.entry import (
    KnowledgeEntry,
    LexicalHit,
    SemanticHit,
)
from app.modules.knowledge.infrastructure.orm.knowledge_entry import (
    KnowledgeEntryRow as Row,
)
from app.shared.contracts.embeddings import QueryVector
from app.shared.contracts.school_knowledge import Audience
from app.shared.db.embeddings import EMBEDDING_DIMS
from app.shared.db.embeddings import Embedding as EmbeddingRow
from app.shared.db.halfvec import HalfVec

from sqlalchemy import Float, and_, delete, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

WORD = re.compile(r"[^\W_]+", re.UNICODE)
MIN_WORD = 3  # shorter words ("is", "of") match almost every entry


def to_entity(row: Row) -> KnowledgeEntry:
    """Map a row to the domain entry."""
    return KnowledgeEntry(
        id=row.id,
        key=row.key,
        value=row.value,
        title=row.title,
        tags=list(row.tags or []),
        author_id=row.author_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        content_hash=None if row.content_hash is None else row.content_hash.strip(),
        accessible_to_guest=row.accessible_to_guest,
        accessible_to_student=row.accessible_to_student,
    )


def _apply(row: Row, entry: KnowledgeEntry) -> None:
    row.key = entry.key
    row.title = entry.title
    row.value = entry.value
    row.tags = list(entry.tags)
    row.author_id = entry.author_id
    row.content_hash = entry.content_hash
    row.accessible_to_guest = entry.accessible_to_guest
    row.accessible_to_student = entry.accessible_to_student


def audience_filter(audience: Audience) -> ColumnElement[bool] | None:
    """The rows an audience may see; staff sees all."""
    if audience == "guest":
        return Row.accessible_to_guest.is_(True)
    if audience == "student":
        return Row.accessible_to_student.is_(True)
    return None


def prefix_query(text: str) -> str | None:
    """A `to_tsquery` string that ORs the words of the text as prefixes, or None."""
    words = [w for w in WORD.findall(text.lower()) if len(w) >= MIN_WORD]
    return " | ".join(f"{word}:*" for word in dict.fromkeys(words)) or None


class SqlEntryRepository:
    """Entries in `knowledge.entries`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def get(self, entry_id: UUID) -> KnowledgeEntry | None:
        """Return the entry or None."""
        row = await self.session.get(Row, entry_id)
        return None if row is None else to_entity(row)

    async def get_by_key(self, key: str) -> KnowledgeEntry | None:
        """Return the entry with this key or None."""
        row = await self.session.scalar(select(Row).where(Row.key == key))
        return None if row is None else to_entity(row)

    async def add(self, entry: KnowledgeEntry) -> None:
        """Insert an entry."""
        row = Row(id=entry.id, created_at=entry.created_at)
        _apply(row, entry)
        row.updated_at = entry.updated_at
        self.session.add(row)
        await self.session.flush()

    async def save(self, entry: KnowledgeEntry) -> None:
        """Write the entry's fields."""
        row = await self.session.get(Row, entry.id)
        if row is not None:
            _apply(row, entry)
            row.updated_at = entry.updated_at
            await self.session.flush()

    async def delete(self, entry_id: UUID) -> None:
        """Delete the entry."""
        await self.session.execute(delete(Row).where(Row.id == entry_id))

    async def list_page(
        self, tags: Sequence[str], limit: int, offset: int
    ) -> tuple[list[KnowledgeEntry], int]:
        """Entries that carry all `tags`, newest change first, and the total."""
        filters = [Row.tags.contains(list(tags))] if tags else []
        total = await self.session.scalar(
            select(func.count()).select_from(Row).where(*filters)
        )
        stmt = (
            select(Row)
            .where(*filters)
            .order_by(Row.updated_at.desc(), Row.id)
            .limit(limit)
            .offset(offset)
        )
        rows = await self.session.scalars(stmt)
        return [to_entity(row) for row in rows], int(total or 0)

    async def search_lexical(
        self,
        query: str,
        min_similarity: float,
        tags: Sequence[str],
        limit: int,
        audience: Audience,
    ) -> list[LexicalHit]:
        """Trigram or full-text matches visible to the audience, best first."""
        q = literal(query)
        similarity = func.greatest(
            func.similarity(Row.key, q),
            func.word_similarity(q, Row.key),
            func.word_similarity(q, Row.value),
            func.word_similarity(q, func.coalesce(Row.title, "")),
            type_=Float,
        ).label("similarity")
        conditions = [similarity >= min_similarity]
        rank: ColumnElement[float] = literal(0.0, Float)
        tsq_text = prefix_query(query)
        if tsq_text is not None:
            tsq = func.to_tsquery("simple", tsq_text)
            conditions.append(Row.search_vector.bool_op("@@")(tsq))
            rank = func.ts_rank(Row.search_vector, tsq, type_=Float)
        stmt = (
            select(Row, similarity, rank.label("rank"))
            .where(or_(*conditions))
            .order_by(rank.desc(), similarity.desc(), Row.updated_at.desc())
            .limit(limit)
        )
        if tags:
            stmt = stmt.where(Row.tags.contains(list(tags)))
        visible = audience_filter(audience)
        if visible is not None:
            stmt = stmt.where(visible)
        result = await self.session.execute(stmt)
        return [LexicalHit(to_entity(r), float(s), float(k)) for r, s, k in result]

    async def search_semantic(
        self,
        vector: QueryVector,
        tags: Sequence[str],
        limit: int,
        audience: Audience,
    ) -> list[SemanticHit]:
        """Entries visible to the audience with a vector of the query's model.

        Nearest first.
        """
        if len(vector.values) != EMBEDDING_DIMS:
            return []
        point = literal(list(vector.values), HalfVec(EMBEDDING_DIMS))
        distance = EmbeddingRow.embedding.op("<=>", return_type=Float)(point)
        near = distance.label("distance")
        stmt = (
            select(Row, near)
            .join(
                EmbeddingRow,
                and_(
                    EmbeddingRow.content_hash == Row.content_hash,
                    EmbeddingRow.model == vector.model,
                ),
            )
            .order_by(near, Row.id)
            .limit(limit)
        )
        if tags:
            stmt = stmt.where(Row.tags.contains(list(tags)))
        visible = audience_filter(audience)
        if visible is not None:
            stmt = stmt.where(visible)
        result = await self.session.execute(stmt)
        return [SemanticHit(to_entity(r), 1.0 - float(d)) for r, d in result]

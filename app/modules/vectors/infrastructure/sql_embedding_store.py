"""SQL store of the vectors (`vectors.embeddings`)."""

from collections.abc import Sequence
from typing import Any, cast

from app.shared.db.embeddings import Embedding

from sqlalchemy import CursorResult, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlEmbeddingStore:
    """One short transaction per call: each call is a single statement."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the session factory."""
        self.sessionmaker = sessionmaker

    async def existing(self, content_hashes: Sequence[str], model: str) -> set[str]:
        """The hashes that already have a vector of the model."""
        if not content_hashes:
            return set()
        stmt = select(Embedding.content_hash).where(
            Embedding.model == model, Embedding.content_hash.in_(content_hashes)
        )
        async with self.sessionmaker() as session:
            return {row.strip() for row in (await session.scalars(stmt)).all()}

    async def put(
        self, model: str, vectors: Sequence[tuple[str, Sequence[float]]]
    ) -> int:
        """Insert new rows; a hash that has a vector of the model is kept as it is."""
        if not vectors:
            return 0
        rows = [
            {
                "content_hash": content_hash,
                "model": model,
                "dims": len(values),
                "embedding": list(values),
            }
            for content_hash, values in vectors
        ]
        stmt = pg_insert(Embedding).values(rows).on_conflict_do_nothing()
        async with self.sessionmaker.begin() as session:
            result = await session.execute(stmt)
        return int(cast("CursorResult[Any]", result).rowcount)

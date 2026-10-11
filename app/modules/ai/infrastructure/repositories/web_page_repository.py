"""SQL store of web pages and cached web queries (`ai.web_pages`, `ai.web_queries`)."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.ai.infrastructure.orm.web_page import WebPageRow, WebQueryRow
from app.modules.ai.ports.web_pages import PageRecord, StoredPage
from app.shared.db.embeddings import EMBEDDING_DIMS
from app.shared.db.embeddings import Embedding as EmbeddingRow
from app.shared.db.halfvec import HalfVec
from app.shared.ids import new_id

from sqlalchemy import Float, and_, delete, literal, select
from sqlalchemy.ext.asyncio import AsyncSession


def _stored(row: WebPageRow) -> StoredPage:
    return StoredPage(
        id=row.id,
        url=row.url,
        site=row.site,
        title=row.title,
        text=row.text,
        highlight=row.highlight or "",
        published_date=row.published_date,
    )


class SqlWebPageRepository:
    """Implements `WebPageStore` on the ai module's session."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session of the unit of work."""
        self.session = session

    async def upsert(
        self, pages: Sequence[PageRecord], now: datetime
    ) -> dict[str, UUID]:
        """Insert the new pages and refresh the known ones in one flush."""
        if not pages:
            return {}
        urls = [page.url for page in pages]
        found = await self.session.execute(
            select(WebPageRow).where(WebPageRow.url.in_(urls))
        )
        rows: dict[str, WebPageRow] = {row.url: row for row in found.scalars()}
        ids: dict[str, UUID] = {}
        for page in pages:
            row = rows.get(page.url)
            if row is None:
                row = WebPageRow(
                    id=new_id(),
                    url=page.url,
                    site=page.site,
                    title=page.title,
                    text=page.text,
                    highlight=page.highlight,
                    published_date=page.published_date,
                    content_hash=page.content_hash,
                    first_seen_at=now,
                    last_seen_at=now,
                    times_returned=1,
                )
                self.session.add(row)
                rows[page.url] = row
            else:
                row.title = page.title
                row.text = page.text
                row.highlight = page.highlight or row.highlight
                row.published_date = page.published_date or row.published_date
                row.content_hash = page.content_hash
                row.last_seen_at = now
                row.times_returned = row.times_returned + 1
            ids[page.url] = row.id
        await self.session.flush()
        return ids

    async def pages(self, ids: Sequence[UUID]) -> list[StoredPage]:
        """The pages of the ids, in the order of the ids."""
        if not ids:
            return []
        found = await self.session.execute(
            select(WebPageRow).where(WebPageRow.id.in_(list(ids)))
        )
        by_id = {row.id: row for row in found.scalars()}
        return [_stored(by_id[page_id]) for page_id in ids if page_id in by_id]

    async def nearest(
        self, model: str, values: Sequence[float], limit: int, min_similarity: float
    ) -> list[tuple[UUID, float]]:
        """Cosine distance from the question to every page vector of the model.

        The stored pages are a few tens of thousands at most, so the distance is exact
        (a scan), which is also what notebooks do for their passages.
        """
        if len(values) != EMBEDDING_DIMS:
            return []
        point = literal(list(values), HalfVec(EMBEDDING_DIMS))
        distance = EmbeddingRow.embedding.op("<=>", return_type=Float)(point)
        stmt = (
            select(WebPageRow.id, distance.label("distance"))
            .select_from(WebPageRow)
            .join(
                EmbeddingRow,
                and_(
                    EmbeddingRow.content_hash == WebPageRow.content_hash,
                    EmbeddingRow.model == model,
                ),
            )
            .where(distance <= 1 - min_similarity)
            .order_by(distance, WebPageRow.id)
            .limit(limit)
        )
        found = await self.session.execute(stmt)
        return [(row.id, 1 - float(row.distance)) for row in found.all()]

    async def cached(self, cache_key: str, since: datetime) -> list[UUID] | None:
        """The ordered ids of a query answered since `since`."""
        stmt = select(WebQueryRow.page_ids).where(
            WebQueryRow.cache_key == cache_key, WebQueryRow.created_at >= since
        )
        ids = (await self.session.execute(stmt)).scalar_one_or_none()
        return list(ids) if ids is not None else None

    async def put_query(
        self, cache_key: str, query: str, ids: Sequence[UUID], now: datetime
    ) -> None:
        """Insert or replace the answer of a query."""
        row = await self.session.get(WebQueryRow, cache_key)
        if row is None:
            self.session.add(
                WebQueryRow(
                    cache_key=cache_key,
                    query=query,
                    page_ids=list(ids),
                    created_at=now,
                )
            )
        else:
            row.query = query
            row.page_ids = list(ids)
            row.created_at = now
        await self.session.flush()

    async def purge_pages(self, cutoff: datetime, limit: int) -> tuple[int, int]:
        """One batch: the old pages, then the vectors no remaining page refers to."""
        old = (
            await self.session.execute(
                select(WebPageRow.id, WebPageRow.content_hash)
                .where(WebPageRow.last_seen_at < cutoff)
                .limit(limit)
            )
        ).all()
        if not old:
            return 0, 0
        hashes = {row.content_hash for row in old}
        await self.session.execute(
            delete(WebPageRow).where(WebPageRow.id.in_([row.id for row in old]))
        )
        kept = await self.session.execute(
            select(WebPageRow.content_hash).where(WebPageRow.content_hash.in_(hashes))
        )
        orphans = hashes - set(kept.scalars())
        vectors = 0
        if orphans:
            result = await self.session.execute(
                delete(EmbeddingRow).where(EmbeddingRow.content_hash.in_(orphans))
            )
            vectors = int(result.rowcount or 0)  # type: ignore[attr-defined]
        await self.session.flush()
        return len(old), vectors

    async def purge_queries(self, cutoff: datetime, limit: int) -> int:
        """One batch of cached queries answered before `cutoff`."""
        keys = (
            await self.session.execute(
                select(WebQueryRow.cache_key)
                .where(WebQueryRow.created_at < cutoff)
                .limit(limit)
            )
        ).scalars()
        chosen = list(keys)
        if not chosen:
            return 0
        await self.session.execute(
            delete(WebQueryRow).where(WebQueryRow.cache_key.in_(chosen))
        )
        await self.session.flush()
        return len(chosen)

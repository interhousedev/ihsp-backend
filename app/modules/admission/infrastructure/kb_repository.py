"""SQL storage of the FAQ knowledge base; Postgres full-text search."""

from uuid import UUID

from app.modules.admission.domain.kb import Article
from app.modules.admission.infrastructure.orm.kb import KbArticleRow

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _article(row: KbArticleRow) -> Article:
    return Article(
        id=row.id,
        title=row.title,
        body=row.body,
        locale=row.locale,
        status=row.status,  # type: ignore[arg-type]
        author_id=row.author_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        tags=list(row.tags or []),
    )


class SqlKbRepository:
    """Each call opens and commits its own session."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self._sm = sessionmaker

    async def get(self, article_id: UUID) -> Article | None:
        """One article or None."""
        async with self._sm() as session:
            row = await session.get(KbArticleRow, article_id)
            return _article(row) if row else None

    async def search(
        self,
        *,
        query: str | None,
        locale: str | None,
        tag: str | None,
        status: str | None,
        limit: int,
    ) -> list[Article]:
        """Matching articles, best match first (newest first without a query)."""
        stmt = select(KbArticleRow)
        if status:
            stmt = stmt.where(KbArticleRow.status == status)
        if locale:
            stmt = stmt.where(KbArticleRow.locale == locale)
        if tag:
            stmt = stmt.where(KbArticleRow.tags.contains([tag.lower()]))
        if query and query.strip():
            tsq = func.plainto_tsquery("simple", query)
            stmt = stmt.where(KbArticleRow.search.op("@@")(tsq)).order_by(
                func.ts_rank(KbArticleRow.search, tsq).desc(),
                KbArticleRow.updated_at.desc(),
            )
        else:
            stmt = stmt.order_by(KbArticleRow.updated_at.desc())
        async with self._sm() as session:
            rows = (await session.scalars(stmt.limit(limit))).all()
        return [_article(r) for r in rows]

    async def add(self, article: Article) -> None:
        """Store a new article."""
        async with self._sm() as session, session.begin():
            session.add(
                KbArticleRow(
                    id=article.id,
                    title=article.title,
                    body=article.body,
                    locale=article.locale,
                    status=article.status,
                    tags=article.tags,
                    author_id=article.author_id,
                    created_at=article.created_at,
                    updated_at=article.updated_at,
                )
            )

    async def save(self, article: Article) -> None:
        """Overwrite an article's fields."""
        async with self._sm() as session, session.begin():
            row = await session.get(KbArticleRow, article.id)
            if row is None:
                return
            row.title = article.title
            row.body = article.body
            row.locale = article.locale
            row.status = article.status
            row.tags = article.tags
            row.updated_at = article.updated_at

    async def delete(self, article_id: UUID) -> bool:
        """Delete an article; False when it did not exist."""
        async with self._sm() as session, session.begin():
            result = await session.execute(
                delete(KbArticleRow).where(KbArticleRow.id == article_id)
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

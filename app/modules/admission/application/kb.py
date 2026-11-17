"""The FAQ knowledge base: everyone in admission reads it, counselors edit it."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.kb import (
    Article,
    ArticleStatus,
    can_edit_kb,
    can_read_kb,
    check_article,
    clean_tags,
)
from app.modules.admission.ports.kb import KbRepository
from app.shared.clock import Clock
from app.shared.ids import new_id

SEARCH_LIMIT = 50


@dataclass(frozen=True, slots=True)
class ArticleDraft:
    """Fields of a new article."""

    title: str
    body: str
    locale: str
    status: ArticleStatus
    tags: list[str]


@dataclass(frozen=True, slots=True)
class ArticleChanges:
    """Fields a PATCH may change; None keeps the value."""

    title: str | None = None
    body: str | None = None
    locale: str | None = None
    status: ArticleStatus | None = None
    tags: list[str] | None = None


class KbService:
    """Read, search and edit FAQ articles."""

    def __init__(self, repo: KbRepository, clock: Clock) -> None:
        """Keep the storage and the clock."""
        self._repo = repo
        self._clock = clock

    @staticmethod
    def may_edit(ctx: AdmissionContext) -> bool:
        """Return whether the caller edits the FAQ (and sees drafts)."""
        return can_edit_kb(ctx.admission, ctx.actor.roles)

    def _require_read(self, ctx: AdmissionContext) -> None:
        if not (can_read_kb(ctx.admission) or self.may_edit(ctx)):
            raise AdmissionForbiddenError(params={"permission": "kb:read"})

    def _require_edit(self, ctx: AdmissionContext) -> None:
        if not self.may_edit(ctx):
            raise AdmissionForbiddenError(params={"permission": "kb:edit"})

    async def search(
        self,
        ctx: AdmissionContext,
        *,
        query: str | None = None,
        locale: str | None = None,
        tag: str | None = None,
        status: ArticleStatus | None = None,
    ) -> list[Article]:
        """Articles the caller may see; drafts only for editors."""
        self._require_read(ctx)
        editor = self.may_edit(ctx)
        if not editor and status not in (None, "published"):
            return []
        return await self._repo.search(
            query=query,
            locale=locale,
            tag=tag,
            status=status if editor else "published",
            limit=SEARCH_LIMIT,
        )

    async def published(
        self, query: str, locale: str | None, limit: int
    ) -> list[Article]:
        """Published matches for the assistant, the locale's first."""
        found = await self._repo.search(
            query=query, locale=None, tag=None, status="published", limit=limit * 3
        )
        found.sort(key=lambda a: a.locale != locale)
        return found[:limit]

    async def get(self, ctx: AdmissionContext, article_id: UUID) -> Article:
        """One article; drafts are hidden from readers."""
        self._require_read(ctx)
        article = await self._repo.get(article_id)
        if article is None or (
            article.status != "published" and not self.may_edit(ctx)
        ):
            raise AdmissionNotFoundError(params={"resource": "kb_article"})
        return article

    async def create(self, ctx: AdmissionContext, draft: ArticleDraft) -> Article:
        """Create an article."""
        self._require_edit(ctx)
        tags = clean_tags(draft.tags)
        check_article(draft.title, draft.body, tags)
        now = self._clock.now()
        article = Article(
            id=new_id(),
            title=draft.title.strip(),
            body=draft.body,
            locale=draft.locale,
            status=draft.status,
            author_id=ctx.user_id,
            created_at=now,
            updated_at=now,
            tags=tags,
        )
        await self._repo.add(article)
        return article

    async def update(
        self, ctx: AdmissionContext, article_id: UUID, changes: ArticleChanges
    ) -> Article:
        """Change an article's fields."""
        self._require_edit(ctx)
        article = await self._repo.get(article_id)
        if article is None:
            raise AdmissionNotFoundError(params={"resource": "kb_article"})
        if changes.title is not None:
            article.title = changes.title.strip()
        if changes.body is not None:
            article.body = changes.body
        if changes.locale is not None:
            article.locale = changes.locale
        if changes.status is not None:
            article.status = changes.status
        if changes.tags is not None:
            article.tags = clean_tags(changes.tags)
        check_article(article.title, article.body, article.tags)
        article.updated_at = self._clock.now()
        await self._repo.save(article)
        return article

    async def delete(self, ctx: AdmissionContext, article_id: UUID) -> None:
        """Delete an article."""
        self._require_edit(ctx)
        if not await self._repo.delete(article_id):
            raise AdmissionNotFoundError(params={"resource": "kb_article"})

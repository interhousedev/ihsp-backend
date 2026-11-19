"""The admission FAQ knowledge base: read by everyone in admission, edited by staff."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AnyContext, ContainerDep
from app.interfaces.http.v1.admission.routes_exemplars import ProblemOut
from app.modules.admission.application.kb import ArticleChanges, ArticleDraft
from app.modules.admission.domain.kb import (
    BODY_MAX,
    TAG_MAX,
    TAGS_MAX,
    TITLE_MAX,
    Article,
    ArticleStatus,
)

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

KbLocale = Annotated[str, Field(pattern="^(uz|ru|en)$")]
Tag = Annotated[str, Field(min_length=1, max_length=TAG_MAX)]


class KbArticleOut(BaseModel):
    """One FAQ article."""

    id: UUID
    title: str
    body: str
    locale: str
    status: ArticleStatus
    tags: list[str]
    author_id: UUID | None
    created_at: datetime
    updated_at: datetime


class KbArticlesOut(BaseModel):
    """Matching articles and whether the caller edits the FAQ."""

    items: list[KbArticleOut]
    can_edit: bool


class KbArticleIn(BaseModel):
    """A new article."""

    title: str = Field(min_length=1, max_length=TITLE_MAX)
    body: str = Field(min_length=1, max_length=BODY_MAX)
    locale: KbLocale
    status: ArticleStatus = "draft"
    tags: list[Tag] = Field(default_factory=list, max_length=TAGS_MAX)


class KbArticlePatch(BaseModel):
    """Changed fields of an article."""

    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    body: str | None = Field(default=None, min_length=1, max_length=BODY_MAX)
    locale: KbLocale | None = None
    status: ArticleStatus | None = None
    tags: list[Tag] | None = Field(default=None, max_length=TAGS_MAX)


def _out(a: Article) -> KbArticleOut:
    return KbArticleOut(
        id=a.id,
        title=a.title,
        body=a.body,
        locale=a.locale,
        status=a.status,
        tags=list(a.tags),
        author_id=a.author_id,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


async def list_articles(
    container: ContainerDep,
    ctx: AnyContext,
    q: Annotated[str | None, Query(max_length=200)] = None,
    locale: Annotated[str | None, Query(pattern="^(uz|ru|en)$")] = None,
    tag: Annotated[str | None, Query(max_length=TAG_MAX)] = None,
    status: ArticleStatus | None = None,
) -> KbArticlesOut:
    """Search the FAQ; drafts only for editors."""
    kb = container.admission.kb
    found = await kb.search(ctx, query=q, locale=locale, tag=tag, status=status)
    return KbArticlesOut(items=[_out(a) for a in found], can_edit=kb.may_edit(ctx))


async def get_article(
    container: ContainerDep, ctx: AnyContext, article_id: UUID
) -> KbArticleOut:
    """One article."""
    return _out(await container.admission.kb.get(ctx, article_id))


async def create_article(
    container: ContainerDep, ctx: AnyContext, body: KbArticleIn
) -> KbArticleOut:
    """Create an article (admins, counselors, mentors)."""
    draft = ArticleDraft(
        title=body.title,
        body=body.body,
        locale=body.locale,
        status=body.status,
        tags=list(body.tags),
    )
    return _out(await container.admission.kb.create(ctx, draft))


async def update_article(
    container: ContainerDep, ctx: AnyContext, article_id: UUID, body: KbArticlePatch
) -> KbArticleOut:
    """Change an article."""
    changes = ArticleChanges(
        title=body.title,
        body=body.body,
        locale=body.locale,
        status=body.status,
        tags=None if body.tags is None else list(body.tags),
    )
    return _out(await container.admission.kb.update(ctx, article_id, changes))


async def delete_article(
    container: ContainerDep, ctx: AnyContext, article_id: UUID
) -> Response:
    """Delete an article."""
    await container.admission.kb.delete(ctx, article_id)
    return Response(status_code=204)


_INVALID = {
    422: {
        "model": ProblemOut,
        "description": (
            "A field breaks a rule, or the body has more than 3 OpenUI blocks, "
            "a block over 6000 characters, a bad block or a link that is not "
            "https, mailto or relative."
        ),
    }
}


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_kb_{op}", **kw
    )


_route("/kb/articles", list_articles, "GET", "list", response_model=KbArticlesOut)
_route(
    "/kb/articles/{article_id}",
    get_article,
    "GET",
    "get",
    response_model=KbArticleOut,
)
_route(
    "/kb/articles",
    create_article,
    "POST",
    "create",
    response_model=KbArticleOut,
    responses=_INVALID,
    status_code=201,
)
_route(
    "/kb/articles/{article_id}",
    update_article,
    "PATCH",
    "update",
    response_model=KbArticleOut,
    responses=_INVALID,
)
_route(
    "/kb/articles/{article_id}",
    delete_article,
    "DELETE",
    "delete",
    status_code=204,
    response_class=Response,
)

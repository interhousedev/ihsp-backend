"""Schemas of /v1/admin/posts."""

from typing import Literal
from uuid import UUID

from app.modules.posts.application.admin_posts import PostNode
from app.modules.posts.domain.post import Post

from pydantic import BaseModel, ConfigDict, Field

AudienceIn = Literal["guest", "student", "both"]


class Localized(BaseModel):
    """Text in uz, ru and en (any may be missing or empty)."""

    model_config = ConfigDict(extra="forbid")

    uz: str | None = Field(default=None, max_length=8000)
    ru: str | None = Field(default=None, max_length=8000)
    en: str | None = Field(default=None, max_length=8000)

    def values(self) -> dict[str, str]:
        """Only the set languages."""
        return {k: v for k, v in self.model_dump().items() if v}


class UrlButtonSchema(BaseModel):
    """An extra link button (https only)."""

    label: Localized
    url: str = Field(max_length=2048)


class PostOut(BaseModel):
    """A post."""

    id: UUID
    parent_id: UUID | None
    slug: str
    title: Localized
    body: Localized
    audience: AudienceIn
    sort_order: int
    published: bool
    is_root: bool
    buttons: list[UrlButtonSchema]

    @classmethod
    def of(cls, post: Post) -> "PostOut":
        """Map a domain post."""
        return cls(
            id=post.id,
            parent_id=post.parent_id,
            slug=post.slug,
            title=Localized(**post.title),
            body=Localized(**post.body),
            audience=post.audience.value,
            sort_order=post.sort_order,
            published=post.published,
            is_root=post.is_root,
            buttons=[
                UrlButtonSchema(label=Localized(**b.label), url=b.url)
                for b in post.buttons
            ],
        )


class PostTreeNode(PostOut):
    """A post with its ordered children."""

    children: list["PostTreeNode"]

    @classmethod
    def of_node(cls, node: PostNode) -> "PostTreeNode":
        """Map a node recursively."""
        base = PostOut.of(node.post).model_dump()
        return cls(**base, children=[cls.of_node(c) for c in node.children])


class PostCreate(BaseModel):
    """A new post; parent_id null puts it under the root."""

    model_config = ConfigDict(extra="forbid")

    parent_id: UUID | None = None
    slug: str = Field(min_length=1, max_length=64)
    title: Localized
    body: Localized = Field(default_factory=Localized)
    audience: AudienceIn = "both"
    sort_order: int | None = None
    published: bool = True
    buttons: list[UrlButtonSchema] = Field(default_factory=list, max_length=8)


class PostPatch(BaseModel):
    """Changed fields only (parent changes go through /move)."""

    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(default=None, min_length=1, max_length=64)
    title: Localized | None = None
    body: Localized | None = None
    audience: AudienceIn | None = None
    sort_order: int | None = None
    published: bool | None = None
    buttons: list[UrlButtonSchema] | None = Field(default=None, max_length=8)


class ReorderBody(BaseModel):
    """The children of a parent (null: the root) in their new order."""

    model_config = ConfigDict(extra="forbid")

    parent_id: UUID | None = None
    ids: list[UUID]


class MoveBody(BaseModel):
    """The new parent (null: the root)."""

    model_config = ConfigDict(extra="forbid")

    parent_id: UUID | None = None


class PostsResponse(BaseModel):
    """A list of posts."""

    items: list[PostOut]

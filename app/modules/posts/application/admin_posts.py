"""Administration of the bot post tree (admin role)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.posts.domain.errors import (
    CycleError,
    HasChildrenError,
    PostNotFoundError,
    ReorderMismatchError,
    RootProtectedError,
    SlugTakenError,
)
from app.modules.posts.domain.post import (
    TITLE_MAX,
    Audience,
    Post,
    Tree,
    UrlButton,
    body_texts,
    buttons_of,
    check_slug,
    localized,
)
from app.modules.posts.ports.repositories import PostRepository
from app.shared.actor import Actor, Role

from uuid_utils.compat import uuid7

ROOT_SLUG = "main-menu"
ROOT_TITLE = {"uz": "Asosiy menyu", "ru": "Главное меню", "en": "Main menu"}


@dataclass(frozen=True, slots=True)
class PostNode:
    """A post with its children (ordered)."""

    post: Post
    children: list["PostNode"]


@dataclass(frozen=True, slots=True)
class PostDraft:
    """A new post; parent_id None means under the root."""

    slug: str
    title: Mapping[str, str]
    body: Mapping[str, str]
    audience: Audience = Audience.BOTH
    parent_id: UUID | None = None
    sort_order: int | None = None
    published: bool = True
    buttons: Sequence[UrlButton] = ()


async def ensure_root(repo: PostRepository) -> Tree:
    """Load the tree; create the root post when there is none."""
    tree = Tree(await repo.list_all())
    if tree.root is None:
        root = Post(
            id=uuid7(),
            parent_id=None,
            slug=ROOT_SLUG,
            title=dict(ROOT_TITLE),
            is_root=True,
        )
        await repo.add(root)
        tree = Tree([*tree.by_id.values(), root])
    return tree


class AdminPosts:
    """Tree, get, create, update, delete, reorder and move."""

    def __init__(self, repo: PostRepository) -> None:
        """Store the repository."""
        self.repo = repo

    async def _tree(self, actor: Actor) -> Tree:
        actor.require(Role.ADMIN)
        return await ensure_root(self.repo)

    @staticmethod
    def _node(tree: Tree, post: Post) -> PostNode:
        return PostNode(
            post, [AdminPosts._node(tree, c) for c in tree.children(post.id)]
        )

    async def tree(self, actor: Actor) -> PostNode:
        """The whole tree from the root."""
        tree = await self._tree(actor)
        assert tree.root is not None
        return self._node(tree, tree.root)

    async def get(self, actor: Actor, post_id: UUID) -> Post:
        """One post."""
        tree = await self._tree(actor)
        return self._find(tree, post_id)

    @staticmethod
    def _find(tree: Tree, post_id: UUID) -> Post:
        post = tree.by_id.get(post_id)
        if post is None:
            raise PostNotFoundError()
        return post

    @staticmethod
    def _slug_free(tree: Tree, slug: str, own: UUID | None = None) -> None:
        if any(p.slug == slug and p.id != own for p in tree.by_id.values()):
            raise SlugTakenError()

    async def create(self, actor: Actor, draft: PostDraft) -> Post:
        """Add a post at the end of its parent (or at sort_order)."""
        tree = await self._tree(actor)
        assert tree.root is not None
        parent_id = draft.parent_id or tree.root.id
        self._find(tree, parent_id)
        slug = check_slug(draft.slug)
        self._slug_free(tree, slug)
        siblings = tree.children(parent_id)
        order = draft.sort_order
        if order is None:
            order = max((p.sort_order for p in siblings), default=-1) + 1
        post = Post(
            id=uuid7(),
            parent_id=parent_id,
            slug=slug,
            title=localized(draft.title, limit=TITLE_MAX, what="title"),
            body=body_texts(draft.body),
            audience=Audience(draft.audience),
            sort_order=order,
            published=draft.published,
            buttons=buttons_of(draft.buttons),
        )
        await self.repo.add(post)
        return post

    async def update(
        self, actor: Actor, post_id: UUID, changes: Mapping[str, Any]
    ) -> Post:
        """Change some fields of a post.

        Fields: slug, title, body, audience, sort_order, published, buttons. The
        root keeps audience `both` and stays published.
        """
        tree = await self._tree(actor)
        post = self._find(tree, post_id)
        fields: dict[str, object] = {}
        if changes.get("slug") is not None:
            fields["slug"] = check_slug(changes["slug"])
            self._slug_free(tree, fields["slug"], post.id)  # type: ignore[arg-type]
        if changes.get("title") is not None:
            fields["title"] = localized(changes["title"], limit=TITLE_MAX, what="title")
        if changes.get("body") is not None:
            fields["body"] = body_texts(changes["body"])
        if changes.get("audience") is not None and not post.is_root:
            fields["audience"] = Audience(changes["audience"])
        if changes.get("sort_order") is not None:
            fields["sort_order"] = int(changes["sort_order"])
        if changes.get("published") is not None and not post.is_root:
            fields["published"] = bool(changes["published"])
        if changes.get("buttons") is not None:
            fields["buttons"] = buttons_of(changes["buttons"])
        updated = post.with_changes(**fields)
        await self.repo.save_many([updated])
        return updated

    async def delete(
        self, actor: Actor, post_id: UUID, *, cascade: bool = False
    ) -> None:
        """Delete a post; refuse the root, and a post with children unless cascade."""
        tree = await self._tree(actor)
        post = self._find(tree, post_id)
        if post.is_root:
            raise RootProtectedError()
        below = tree.descendants(post.id)
        if below and not cascade:
            raise HasChildrenError(params={"children": len(tree.children(post.id))})
        await self.repo.delete_many([*below, post.id])

    async def reorder(
        self, actor: Actor, parent_id: UUID | None, ids: Sequence[UUID]
    ) -> list[Post]:
        """Set the order of all children of a parent (None: the root)."""
        tree = await self._tree(actor)
        assert tree.root is not None
        parent = self._find(tree, parent_id or tree.root.id)
        children = tree.children(parent.id)
        if len(ids) != len(set(ids)) or set(ids) != {c.id for c in children}:
            raise ReorderMismatchError()
        posts = [tree.by_id[i].with_changes(sort_order=n) for n, i in enumerate(ids)]
        await self.repo.save_many(posts)
        return posts

    async def move(self, actor: Actor, post_id: UUID, parent_id: UUID | None) -> Post:
        """Move a post (with its subtree) to the end of another parent."""
        tree = await self._tree(actor)
        assert tree.root is not None
        post = self._find(tree, post_id)
        if post.is_root:
            raise RootProtectedError()
        target = self._find(tree, parent_id or tree.root.id)
        if target.id == post.id or target.id in tree.descendants(post.id):
            raise CycleError()
        if target.id == post.parent_id:
            return post
        order = max((p.sort_order for p in tree.children(target.id)), default=-1) + 1
        moved = post.with_changes(parent_id=target.id, sort_order=order)
        await self.repo.save_many([moved])
        return moved

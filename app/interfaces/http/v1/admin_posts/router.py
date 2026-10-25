"""Routes /v1/admin/posts: the bot post tree (admin only)."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_posts.schemas import (
    MoveBody,
    PostCreate,
    PostOut,
    PostPatch,
    PostsResponse,
    PostTreeNode,
    ReorderBody,
    UrlButtonSchema,
)
from app.modules.posts.application.admin_posts import PostDraft
from app.modules.posts.domain.post import Audience, UrlButton
from app.shared.actor import Actor, Role

from fastapi import APIRouter, Depends, Query, Response, status

router = APIRouter(prefix="/v1/admin/posts", tags=["admin-posts"])

ContainerDep = Annotated[Container, Depends(get_container)]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]


def _buttons(items: list[UrlButtonSchema]) -> list[UrlButton]:
    return [UrlButton.of(b.label.values(), b.url) for b in items]


@router.get("/tree", response_model=PostTreeNode)
async def get_tree(container: ContainerDep, actor: AdminActor) -> PostTreeNode:
    """The whole tree from the root (main menu); creates the root on first use."""
    node = await container.posts.admin.tree(actor)
    return PostTreeNode.of_node(node)


@router.get("/{post_id}", response_model=PostOut)
async def get_post(
    post_id: UUID, container: ContainerDep, actor: AdminActor
) -> PostOut:
    """One post."""
    return PostOut.of(await container.posts.admin.get(actor, post_id))


@router.post("", response_model=PostOut, status_code=status.HTTP_201_CREATED)
async def create_post(
    body: PostCreate, container: ContainerDep, actor: AdminActor
) -> PostOut:
    """Add a post (at the end of its parent unless sort_order is given)."""
    draft = PostDraft(
        slug=body.slug,
        title=body.title.values(),
        body=body.body.values(),
        audience=Audience(body.audience),
        parent_id=body.parent_id,
        sort_order=body.sort_order,
        published=body.published,
        buttons=_buttons(body.buttons),
    )
    return PostOut.of(await container.posts.admin.create(actor, draft))


@router.patch("/{post_id}", response_model=PostOut)
async def patch_post(
    post_id: UUID, body: PostPatch, container: ContainerDep, actor: AdminActor
) -> PostOut:
    """Change some fields of a post."""
    changes: dict[str, object] = body.model_dump(exclude_unset=True)
    for key in ("title", "body"):
        value = getattr(body, key)
        changes[key] = value.values() if value is not None else None
    if body.buttons is not None:
        changes["buttons"] = _buttons(body.buttons)
    return PostOut.of(await container.posts.admin.update(actor, post_id, changes))


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: UUID,
    container: ContainerDep,
    actor: AdminActor,
    cascade: Annotated[bool, Query()] = False,
) -> Response:
    """Delete a post; 409 for the root, and for a post with children unless cascade."""
    await container.posts.admin.delete(actor, post_id, cascade=cascade)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reorder", response_model=PostsResponse)
async def reorder_posts(
    body: ReorderBody, container: ContainerDep, actor: AdminActor
) -> PostsResponse:
    """Set the order of all children of a parent; ids must be exactly those children."""
    posts = await container.posts.admin.reorder(actor, body.parent_id, body.ids)
    return PostsResponse(items=[PostOut.of(p) for p in posts])


@router.post("/{post_id}/move", response_model=PostOut)
async def move_post(
    post_id: UUID, body: MoveBody, container: ContainerDep, actor: AdminActor
) -> PostOut:
    """Move a post with its subtree under another parent (no cycles, not the root)."""
    return PostOut.of(await container.posts.admin.move(actor, post_id, body.parent_id))

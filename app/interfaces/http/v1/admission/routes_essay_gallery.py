"""The essay gallery: publish a version, browse others' essays, fork a target."""

import datetime as dt
from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admission.deps import ContainerDep, StudentCtx
from app.interfaces.http.v1.admission.routes_essays import EssayOut, PromptTargetOut
from app.modules.admission.application.essay_gallery import (
    BROWSE_LIMIT,
    GalleryItem,
)

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class GalleryItemOut(BaseModel):
    """A published essay version; it never carries the author."""

    essay_id: UUID
    kind: str
    title: str
    prompt_text: str
    word_limit: int | None
    targets: list[PromptTargetOut]
    version: int
    body: str
    word_count: int
    published_at: dt.datetime | None


class GalleryOut(BaseModel):
    """`items`: others' essays; `mine`: what the student published."""

    items: list[GalleryItemOut]
    mine: list[GalleryItemOut]


class ForkIn(BaseModel):
    """The prompt of the group the new essay takes (`null` owner: Common App)."""

    institution_id: UUID | None = None
    position: int = Field(ge=1)


class ForkOut(BaseModel):
    """`parent` without the taken target; `essay` is the new fork."""

    parent: EssayOut
    essay: EssayOut


def _item(i: GalleryItem) -> GalleryItemOut:
    return GalleryItemOut(
        essay_id=i.essay_id,
        kind=i.kind,
        title=i.title,
        prompt_text=i.prompt_text,
        word_limit=i.word_limit,
        targets=[
            PromptTargetOut(
                institution_id=t.institution_id,
                position=t.position,
                prompt=t.prompt,
                word_limit=t.word_limit,
            )
            for t in i.targets
        ],
        version=i.version,
        body=i.body,
        word_count=i.word_count,
        published_at=i.published_at,
    )


async def browse_gallery(
    container: ContainerDep,
    ctx: StudentCtx,
    limit: Annotated[int, Query(ge=1, le=100)] = BROWSE_LIMIT,
) -> GalleryOut:
    """Others' published essays (anonymous) and my own."""
    view = await container.admission.essay_gallery.browse(ctx, limit)
    return GalleryOut(
        items=[_item(i) for i in view.items], mine=[_item(i) for i in view.mine]
    )


async def publish_essay(
    essay_id: UUID, container: ContainerDep, ctx: StudentCtx
) -> GalleryItemOut:
    """Publish the current text of my essay as a new version (needs sharing)."""
    return _item(await container.admission.essay_gallery.publish(ctx, essay_id))


async def unpublish_essay(
    essay_id: UUID, container: ContainerDep, ctx: StudentCtx
) -> Response:
    """Take my essay out of the gallery."""
    await container.admission.essay_gallery.unpublish(ctx, essay_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def fork_essay(
    essay_id: UUID, body: ForkIn, container: ContainerDep, ctx: StudentCtx
) -> ForkOut:
    """Copy the body into a new essay for one target of the group."""
    parent, child = await container.admission.essay_gallery.fork(
        ctx, essay_id, body.institution_id, body.position
    )
    return ForkOut(parent=EssayOut.of(parent), essay=EssayOut.of(child))


router.add_api_route(
    "/essays/gallery",
    browse_gallery,
    methods=["GET"],
    operation_id="admission_essay_gallery",
    response_model=GalleryOut,
)
router.add_api_route(
    "/essays/{essay_id}/gallery",
    publish_essay,
    methods=["POST"],
    operation_id="admission_essay_publish",
    response_model=GalleryItemOut,
)
router.add_api_route(
    "/essays/{essay_id}/gallery",
    unpublish_essay,
    methods=["DELETE"],
    operation_id="admission_essay_unpublish",
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/essays/{essay_id}/fork",
    fork_essay,
    methods=["POST"],
    operation_id="admission_essay_fork",
    response_model=ForkOut,
    status_code=status.HTTP_201_CREATED,
)

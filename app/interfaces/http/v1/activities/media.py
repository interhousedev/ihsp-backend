"""Club albums and media: upload, browse, move, report, and the signed file route."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.activities.deps import ActorDep, ContainerDep
from app.interfaces.http.v1.activities.schemas_media import (
    AlbumIn,
    AlbumListOut,
    AlbumOut,
    AlbumPatch,
    BatchIn,
    MediaListOut,
    MediaOut,
    MediaPageOut,
    MediaPatch,
    ReportIn,
    UploadIn,
    UploadOut,
    UsageOut,
    upload_out,
)
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.media import MediaKind, MediaVariant

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/v1/activities", tags=["activities"])

# Signed URLs live one to two hours and every open re-checks the item, so the
# browser keeps the bytes 10 minutes only (a takedown reaches everyone quickly)
# and no shared cache stores them.
STREAM_CACHE = "private, max-age=600"


@router.post("/clubs/{club_id}/media:request-upload", status_code=201)
async def request_upload(
    club_id: UUID, body: UploadIn, container: ContainerDep, actor: ActorDep
) -> UploadOut:
    """Reserve an item and get a presigned PUT for its bytes."""
    svc = container.activities.media
    started = await svc.request_upload(actor, club_id, **body.model_dump())
    (view,) = await svc.views(actor, [started.media])
    return upload_out(started, view)


@router.post("/media/{media_id}:complete")
async def complete_upload(
    media_id: UUID, container: ContainerDep, actor: ActorDep
) -> MediaOut:
    """The bytes are uploaded; processing starts."""
    return MediaOut.of(await container.activities.media.complete(actor, media_id))


@router.post("/media:batch")
async def batch(
    body: BatchIn, container: ContainerDep, actor: ActorDep
) -> MediaListOut:
    """Move or delete several items of one club."""
    svc = container.activities.media
    if body.action == "move":
        if body.album_id is None:
            raise ActivitiesNotFoundError()
        views = await svc.move(actor, body.ids, body.album_id)
        return MediaListOut(items=[MediaOut.of(v) for v in views])
    for mid in body.ids:
        await svc.delete(actor, mid)
    return MediaListOut(items=[])


@router.get("/media/{media_id}")
async def get_media(
    media_id: UUID, container: ContainerDep, actor: ActorDep
) -> MediaOut:
    """One item (poll while it is processing)."""
    return MediaOut.of(await container.activities.media.get(actor, media_id))


@router.patch("/media/{media_id}")
async def update_media(
    media_id: UUID, body: MediaPatch, container: ContainerDep, actor: ActorDep
) -> MediaOut:
    """Caption, album, or the uploader's own hide/show."""
    svc = container.activities.media
    sent = body.model_fields_set
    view = None
    if "caption" in sent:
        view = await svc.update(actor, media_id, caption=body.caption)
    if body.album_id is not None:
        view = await svc.attach(actor, media_id, body.album_id)
    if body.hidden is not None:
        view = await svc.set_hidden(actor, media_id, body.hidden)
    return MediaOut.of(view or await svc.get(actor, media_id))


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    media_id: UUID, container: ContainerDep, actor: ActorDep
) -> Response:
    """Delete an own item (or any, for moderators)."""
    await container.activities.media.delete(actor, media_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/media/{media_id}:report", status_code=status.HTTP_204_NO_CONTENT)
async def report_media(
    media_id: UUID, body: ReportIn, container: ContainerDep, actor: ActorDep
) -> Response:
    """Report an item; "I am in this photo" hides it at once."""
    await container.activities.media.report(
        actor, media_id, reason=body.reason, is_subject=body.is_subject
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/media/{media_id}/{variant}",
    response_class=Response,
    responses={
        200: {"content": {"image/webp": {}}},
        302: {"description": "Presigned storage URL"},
        404: {"description": "Bad or expired signature, or item not served"},
    },
)
async def media_file(
    media_id: UUID,
    variant: str,
    container: ContainerDep,
    e: Annotated[int | None, Query()] = None,
    s: Annotated[str | None, Query(max_length=128)] = None,
) -> Response:
    """Signed file route: no Bearer; the signature and the item state decide."""
    if e is None or s is None or variant not in MediaVariant:
        raise ActivitiesNotFoundError()
    svc = container.activities.media
    served = await svc.open_variant(media_id, MediaVariant(variant), e, s)
    if served.redirect:
        return RedirectResponse(
            await svc.variant_url(served.file_id),
            status_code=status.HTTP_302_FOUND,
            headers={"Cache-Control": "no-store"},
        )
    data = await svc.read_variant(served.file_id)
    return Response(
        data,
        media_type=served.content_type,
        headers={
            "Cache-Control": STREAM_CACHE,
            "ETag": f'"{served.file_id}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/clubs/{club_id}/albums")
async def list_albums(
    club_id: UUID,
    container: ContainerDep,
    actor: ActorDep,
    parent_id: UUID | None = None,
) -> AlbumListOut:
    """Albums under a parent (root when omitted) that the caller may see."""
    rows = await container.activities.media.list_albums(actor, club_id, parent_id)
    return AlbumListOut(items=[AlbumOut.of(a) for a in rows])


@router.post("/clubs/{club_id}/albums", status_code=status.HTTP_201_CREATED)
async def create_album(
    club_id: UUID, body: AlbumIn, container: ContainerDep, actor: ActorDep
) -> AlbumOut:
    """A new album."""
    data = body.model_dump()
    title = data.pop("title")
    view = await container.activities.media.create_album(actor, club_id, title, **data)
    return AlbumOut.of(view)


@router.get("/clubs/{club_id}/media/usage")
async def media_usage(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> UsageOut:
    """Storage use and limits of the club."""
    return UsageOut.of(await container.activities.media.usage(actor, club_id))


@router.get("/events/{event_id}/album")
async def event_album(
    event_id: UUID, container: ContainerDep, actor: ActorDep
) -> AlbumOut | None:
    """The event's album, or null."""
    view = await container.activities.media.event_album(actor, event_id)
    return AlbumOut.of(view) if view else None


@router.put("/events/{event_id}/album")
async def ensure_event_album(
    event_id: UUID, container: ContainerDep, actor: ActorDep
) -> AlbumOut:
    """Create the event's album if missing (idempotent)."""
    return AlbumOut.of(
        await container.activities.media.ensure_event_album(actor, event_id)
    )


@router.get("/albums/{album_id}")
async def get_album(
    album_id: UUID, container: ContainerDep, actor: ActorDep
) -> AlbumOut:
    """One album."""
    return AlbumOut.of(await container.activities.media.get_album(actor, album_id))


@router.patch("/albums/{album_id}")
async def update_album(
    album_id: UUID, body: AlbumPatch, container: ContainerDep, actor: ActorDep
) -> AlbumOut:
    """Album fields."""
    view = await container.activities.media.update_album(
        actor, album_id, **body.model_dump(exclude_unset=True)
    )
    return AlbumOut.of(view)


@router.delete("/albums/{album_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_album(
    album_id: UUID, container: ContainerDep, actor: ActorDep
) -> Response:
    """Delete an album and its items (soft)."""
    await container.activities.media.delete_album(actor, album_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/albums/{album_id}/media")
async def album_media(
    album_id: UUID,
    container: ContainerDep,
    actor: ActorDep,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 60,
    kind: MediaKind | None = None,
) -> MediaPageOut:
    """Items of an album, oldest position first."""
    page = await container.activities.media.list_media(
        actor, album_id, kind=kind, cursor=cursor, limit=limit
    )
    return MediaPageOut(
        items=[MediaOut.of(v) for v in page.items], next_cursor=page.next_cursor
    )

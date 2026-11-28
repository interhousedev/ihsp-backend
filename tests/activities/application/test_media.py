"""Club media: permissions, quota, post-moderation, reports, idempotent import."""

import base64
import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID

from app.modules.activities.domain.access import PermissionDeniedError
from app.modules.activities.domain.club import Club
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.media import (
    AlbumVisibility,
    MediaDuplicateError,
    MediaKind,
    MediaQuotaExceededError,
    MediaStatus,
    MediaUploadBlockedError,
    MediaVariant,
)
from app.shared.actor import Actor
from tests.fakes.activities.world import ActivitiesWorld

import pytest


def _sha(n: int) -> str:
    return base64.b64encode(hashlib.sha256(str(n).encode()).digest()).decode()


async def _upload(
    world: ActivitiesWorld,
    actor: Actor,
    club: Club,
    n: int,
    size: int = 400,
    album_id: UUID | None = None,
) -> UUID:
    svc = world.services.media
    started = await svc.request_upload(
        actor,
        club.id,
        name=f"p{n}.jpg",
        size=size,
        content_type="image/jpeg",
        sha256_b64=_sha(n),
        consent_attested=True,
        album_id=album_id,
    )
    await svc.complete(actor, started.media.id)
    await svc.process(started.media.id)
    media_id: UUID = started.media.id
    return media_id


async def test_non_organizer_cannot_upload(
    world: ActivitiesWorld, club: Club, student: Actor
) -> None:
    with pytest.raises(PermissionDeniedError):
        await world.services.media.request_upload(
            student,
            club.id,
            name="a.jpg",
            size=10,
            content_type="image/jpeg",
            sha256_b64=_sha(1),
            consent_attested=True,
        )


async def test_media_of_other_club_refused(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    mid = await _upload(world, owner, club, 1)  # staged: only the uploader sees it
    with pytest.raises(ActivitiesNotFoundError):
        await world.services.media.get(student, mid)
    assert (
        await world.services.media.get(owner, mid)
    ).media.status == MediaStatus.READY


async def test_upload_visible_immediately_after_processing(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    svc = world.services.media
    album = await svc.create_album(owner, club.id, "Trip")
    mid = await _upload(world, owner, club, 1, album_id=album.album.id)
    page = await svc.list_media(student, album.album.id)
    assert [v.media.id for v in page.items] == [mid]
    assert page.items[0].thumb_url and page.items[0].media.kind == MediaKind.PHOTO


async def test_quota_exceeded_with_club_override(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    svc = world.services.media
    await _upload(world, owner, club, 1)
    await _upload(world, owner, club, 2)
    with pytest.raises(MediaQuotaExceededError):
        await _upload(world, owner, club, 3)
    await svc.set_club_limits(su, club.id, quota_bytes=5000)
    await _upload(world, owner, club, 3)
    with pytest.raises(PermissionDeniedError):
        await svc.set_club_limits(owner, club.id, quota_bytes=9000)
    usage = await svc.set_club_limits(su, club.id)
    assert usage.overrides.quota_bytes is None


async def test_duplicate_refused(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    album = await world.services.media.create_album(owner, club.id, "Trip")
    await _upload(world, owner, club, 1, size=10, album_id=album.album.id)
    with pytest.raises(MediaDuplicateError):
        await _upload(world, owner, club, 1, size=10, album_id=album.album.id)


async def test_restore_respects_quota(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    svc = world.services.media
    first = await _upload(world, owner, club, 1)
    await _upload(world, owner, club, 2)
    await svc.delete(owner, first)
    await _upload(world, owner, club, 3)
    with pytest.raises(MediaQuotaExceededError):
        await svc.undelete(owner, first)
    with pytest.raises(ActivitiesNotFoundError):  # still deleted
        await svc.get(owner, first)


async def test_complete_rechecks_quota_and_drops_upload(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    svc = world.services.media
    started = await svc.request_upload(
        owner,
        club.id,
        name="p1.jpg",
        size=400,
        content_type="image/jpeg",
        sha256_b64=_sha(1),
        consent_attested=True,
    )
    await svc.set_club_limits(su, club.id, quota_bytes=300)
    with pytest.raises(MediaQuotaExceededError):
        await svc.complete(owner, started.media.id)
    with pytest.raises(ActivitiesNotFoundError):
        await svc.get(owner, started.media.id)
    assert started.media.original_file_id in world.media_store.deleted


def _signed(url: str) -> tuple[MediaVariant, int, str]:
    path, query = url.split("?")
    q = dict(kv.split("=") for kv in query.split("&"))
    return MediaVariant(path.rsplit("/", 1)[1]), int(q["e"]), q["s"]


async def test_signed_url_rechecks_album_audience_and_state(
    world: ActivitiesWorld, club: Club, owner: Actor
) -> None:
    svc = world.services.media
    album = await svc.create_album(owner, club.id, "Trip")
    mid = await _upload(world, owner, club, 1, size=10, album_id=album.album.id)
    url = (await svc.get(owner, mid)).thumb_url
    assert url is not None
    await svc.open_variant(mid, *_signed(url))
    await svc.update_album(owner, album.album.id, visibility=AlbumVisibility.MEMBERS)
    with pytest.raises(ActivitiesNotFoundError):
        await svc.open_variant(mid, *_signed(url))
    fresh = (await svc.get(owner, mid)).thumb_url
    assert fresh is not None and fresh != url
    await svc.open_variant(mid, *_signed(fresh))
    await svc.set_hidden(owner, mid, True)
    with pytest.raises(ActivitiesNotFoundError):
        await svc.open_variant(mid, *_signed(fresh))
    await svc.set_hidden(owner, mid, False)
    await svc.delete_album(owner, album.album.id)
    with pytest.raises(ActivitiesNotFoundError):
        await svc.open_variant(mid, *_signed(fresh))


async def test_report_hides_instantly(
    world: ActivitiesWorld, club: Club, owner: Actor, student: Actor
) -> None:
    svc = world.services.media
    album = await svc.create_album(owner, club.id, "Trip")
    mid = await _upload(world, owner, club, 1, size=10, album_id=album.album.id)
    await svc.report(student, mid, reason="me", is_subject=True)
    assert (await svc.list_media(student, album.album.id)).items == []
    with pytest.raises(ActivitiesNotFoundError):
        await svc.get(student, mid)
    assert (await svc.get(owner, mid)).media.status == MediaStatus.HIDDEN
    queue = await svc.review_queue(owner, club_id=club.id)
    assert [v.media.id for v in queue.items] == [mid]


async def test_import_is_idempotent_by_source_ref(
    world: ActivitiesWorld, club: Club, su: Actor, owner: Actor
) -> None:
    svc = world.services.media
    a1 = await svc.upsert_album(su, club.id, source_ref="arch:1", title="Old")
    a2 = await svc.upsert_album(su, club.id, source_ref="arch:1", title="Old2")
    assert a1.id == a2.id and a2.title == "Old2"
    kw: dict[str, Any] = {
        "source_ref": "arch:1:p1",
        "kind": MediaKind.PHOTO,
        "original_file_id": a1.id,
        "byte_size": 5,
        "sha256_hex": "ab" * 32,
    }
    m1, created1 = await svc.import_media(su, club.id, a1.id, **kw)
    m2, created2 = await svc.import_media(su, club.id, a1.id, **kw)
    assert created1 and not created2 and m1.id == m2.id


async def test_blocked_uploader_refused(
    world: ActivitiesWorld, club: Club, owner: Actor, su: Actor
) -> None:
    await world.services.media.block_uploader(su, owner.user_id, club_id=club.id)
    with pytest.raises(MediaUploadBlockedError):
        await _upload(world, owner, club, 1)


async def test_video_keeps_playable_copy_and_serves_signed_variants(
    world: ActivitiesWorld,
    club: Club,
    owner: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.activities.domain.media import MediaVariant
    from app.modules.activities.ports.gateways import Derivative, MediaProbe

    async def probe(path: Path) -> MediaProbe:
        return MediaProbe(MediaKind.VIDEO, "video/mp4", 64, 36, 1000)

    async def derive(path: Path, probe_: MediaProbe, out_dir: Path) -> list[Derivative]:
        out_dir.mkdir(parents=True, exist_ok=True)
        made = []
        for variant, ext in (
            (MediaVariant.THUMB, "webp"),
            (MediaVariant.POSTER, "webp"),
            (MediaVariant.VIDEO, "mp4"),
        ):
            f = out_dir / f"{variant.value}.{ext}"
            f.write_bytes(b"v" * 10)
            made.append(Derivative(variant, f, "x", 64, 36))
        return made

    monkeypatch.setattr(world.media_processor, "probe", probe)
    monkeypatch.setattr(world.media_processor, "make_derivatives", derive)
    svc = world.services.media
    started = await svc.request_upload(
        owner,
        club.id,
        name="clip.mp4",
        size=400,
        content_type="video/mp4",
        sha256_b64=_sha(9),
        consent_attested=True,
    )
    await svc.complete(owner, started.media.id)
    await svc.process(started.media.id)
    view = await svc.get(owner, started.media.id)
    m = view.media
    assert m.status == MediaStatus.READY and m.kind == MediaKind.VIDEO
    assert m.preview_file_id is not None and m.poster_file_id is not None
    assert view.video_url and view.poster_url and view.preview_url is None

    def parts(url: str) -> tuple[MediaVariant, int, str]:
        path, query = url.split("?")
        q = dict(kv.split("=") for kv in query.split("&"))
        return MediaVariant(path.rsplit("/", 1)[1]), int(q["e"]), q["s"]

    variant, exp, sig = parts(view.video_url)
    served = await svc.open_variant(m.id, variant, exp, sig)
    assert served.redirect and served.file_id == m.preview_file_id
    assert view.thumb_url is not None
    variant, exp, sig = parts(view.thumb_url)
    served = await svc.open_variant(m.id, variant, exp, sig)
    assert not served.redirect and served.file_id == m.thumb_file_id
    with pytest.raises(ActivitiesNotFoundError):
        await svc.open_variant(m.id, MediaVariant.THUMB, exp, "0" * 64)
    with pytest.raises(ActivitiesNotFoundError):
        await svc.open_variant(m.id, MediaVariant.PREVIEW, exp, sig)

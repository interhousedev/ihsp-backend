"""Faces: own face, staff lock, devices, entrance identify, purge."""

from datetime import timedelta
from uuid import UUID

from app.modules.faces.domain.device_token import hash_token
from app.modules.faces.domain.errors import (
    DeviceUnauthorizedError,
    FaceImageEmptyError,
    FaceImageTooLargeError,
    FaceImageTypeError,
    FaceLockedError,
    FaceNotCuratorError,
    NoFaceError,
)
from app.modules.faces.domain.image import MAX_IMAGE_BYTES
from app.modules.faces.domain.models import (
    CallStatus,
    DeviceCall,
    Direction,
    Passage,
)
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.faces.conftest import PNG, FacesHarness, photo
from tests.fakes.clock import FixedClock

import pytest


def student_actor(fh: FacesHarness, name: str = "Ali Karimov") -> Actor:
    """A student known to the directory, with a matching actor."""
    info = fh.directory.add_student(name)
    return Actor(user_id=info.user_id, roles=frozenset({Role.STUDENT}))


# --- lock rule -----------------------------------------------------------------


async def test_student_uploads_and_replaces_own_face(fh: FacesHarness) -> None:
    me = student_actor(fh)
    view = await fh.services.upload_my_face.execute(me.user_id, photo("a"))
    assert view.has_face and not view.locked
    await fh.services.upload_my_face.execute(me.user_id, photo("b"))
    assert len(fh.files.files) == 1  # the old photo was deleted


async def test_staff_upload_locks_student_out(fh: FacesHarness) -> None:
    me = student_actor(fh)
    fh.directory.curators.add(
        (fh.curator.user_id, fh.directory.students[me.user_id].group_id)
    )
    view = await fh.services.staff_upload.execute(fh.curator, me.user_id, photo("s"))
    assert view.locked
    with pytest.raises(FaceLockedError):
        await fh.services.upload_my_face.execute(me.user_id, photo("x"))
    with pytest.raises(FaceLockedError):
        await fh.services.delete_my_face.execute(me.user_id)
    replaced = await fh.services.staff_upload.execute(fh.admin, me.user_id, photo("t"))
    assert replaced.locked
    await fh.services.staff_delete.execute(fh.admin, me.user_id)
    assert (await fh.services.get_my_face.execute(me.user_id)).has_face is False


async def test_only_the_curator_or_admin_may_set_a_face(fh: FacesHarness) -> None:
    me = student_actor(fh)
    with pytest.raises(FaceNotCuratorError):
        await fh.services.staff_upload.execute(fh.curator, me.user_id, photo("s"))


# --- image checks --------------------------------------------------------------


async def test_upload_sniff_and_size_limits(fh: FacesHarness) -> None:
    me = student_actor(fh)
    up = fh.services.upload_my_face
    with pytest.raises(FaceImageEmptyError):
        await up.execute(me.user_id, b"")
    with pytest.raises(FaceImageTypeError):
        await up.execute(me.user_id, b"GIF89a....")
    with pytest.raises(FaceImageTooLargeError):
        await up.execute(me.user_id, PNG + b"0" * MAX_IMAGE_BYTES)
    with pytest.raises(NoFaceError):
        await up.execute(me.user_id, photo("NOFACE"))
    await up.execute(me.user_id, b"\xff\xd8\xff" + b"jpeg")  # jpeg is fine


# --- devices -------------------------------------------------------------------


async def test_device_token_is_stored_as_hash_only(fh: FacesHarness) -> None:
    created = await fh.services.create_device.execute(fh.admin.user_id, " Door 1 ")
    stored = fh.store.devices[created.id]
    assert created.token.startswith("ihsp_dev_") and created.name == "Door 1"
    assert stored.key_hash == hash_token(created.token)
    assert created.token not in repr(stored)
    assert created.token.startswith(stored.key_prefix)


async def test_revoked_device_is_refused_and_last_used_is_set(
    fh: FacesHarness, clock: FixedClock
) -> None:
    created = await fh.services.create_device.execute(fh.admin.user_id, "Door")
    await fh.services.identify.execute(created.token, Direction.IN, photo("n"))
    assert fh.store.devices[created.id].last_used_at == clock.now()
    revoked = await fh.services.revoke_device.execute(created.id)
    assert revoked.revoked_at is not None
    with pytest.raises(DeviceUnauthorizedError):
        await fh.services.identify.execute(created.token, Direction.IN, photo("n"))
    with pytest.raises(DeviceUnauthorizedError):
        await fh.services.identify.execute("nonsense", Direction.IN, photo("n"))


# --- identify ------------------------------------------------------------------


async def enrolled(fh: FacesHarness, tag: str = "ali") -> tuple[UUID, str]:
    """Enrol a student and return their id and a device token."""
    me = student_actor(fh)
    await fh.services.upload_my_face.execute(me.user_id, photo(tag))
    created = await fh.services.create_device.execute(fh.admin.user_id, "Door")
    return me.user_id, created.token


async def test_identify_match_and_no_match(fh: FacesHarness) -> None:
    user_id, token = await enrolled(fh)
    fh.excuses.excused = True
    fh.excuses.until = fh.clock.now().date()
    hit = await fh.services.identify.execute(token, Direction.IN, photo("ali"))
    assert hit.student is not None and hit.student.id == user_id
    assert hit.student.group == "2TN2" and hit.excused
    assert hit.excuse_until == fh.clock.now().date().isoformat()
    miss = await fh.services.identify.execute(token, Direction.IN, photo("stranger"))
    assert miss.student is None and not miss.excused
    none = await fh.services.identify.execute(token, Direction.IN, photo("NOFACE"))
    assert none.student is None
    statuses = [c.status for c in fh.store.calls]
    assert statuses == [CallStatus.MATCHED, CallStatus.NO_MATCH, CallStatus.NO_FACE]
    assert len(fh.store.passages) == 1


async def test_unexcused_exit_in_lesson_notifies_curator(fh: FacesHarness) -> None:
    _, token = await enrolled(fh)
    fh.excuses.in_lesson = True
    fh.excuses.curator_id = fh.curator.user_id
    await fh.services.identify.execute(token, Direction.IN, photo("ali"))
    assert fh.store.notifications == []
    await fh.services.identify.execute(token, Direction.OUT, photo("ali"))
    [draft] = fh.store.notifications
    assert draft.type is NotificationType.GATE_UNEXCUSED_EXIT
    assert draft.user_id == fh.curator.user_id


async def test_excused_or_out_of_lesson_exit_does_not_notify(fh: FacesHarness) -> None:
    _, token = await enrolled(fh)
    fh.excuses.curator_id = fh.curator.user_id
    fh.excuses.in_lesson = True
    fh.excuses.excused = True
    await fh.services.identify.execute(token, Direction.OUT, photo("ali"))
    fh.excuses.excused = False
    fh.excuses.in_lesson = False
    await fh.services.identify.execute(token, Direction.OUT, photo("ali"))
    assert fh.store.notifications == []


# --- calls and purge -----------------------------------------------------------


async def test_calls_cover_seven_days_and_purge_drops_older(
    fh: FacesHarness, clock: FixedClock
) -> None:
    created = await fh.services.create_device.execute(fh.admin.user_id, "Door")
    now = clock.now()
    old = now - timedelta(days=8)
    fh.store.calls.append(
        DeviceCall(new_id(), created.id, old, CallStatus.NO_MATCH, None, None)
    )
    fh.store.passages.append(
        Passage(new_id(), created.id, new_id(), old, Direction.IN, False)
    )
    await fh.services.identify.execute(created.token, Direction.IN, photo("z"))
    calls = await fh.services.list_calls.execute(created.id)
    assert len(calls) == 1
    removed = await fh.services.purge_old.execute()
    assert removed == 2
    assert len(fh.store.calls) == 1 and fh.store.passages == []


def _png_header(width: int, height: int) -> bytes:
    import struct

    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x02\x00\x00\x00"
    )


def _jpeg_header(width: int, height: int) -> bytes:
    import struct

    return (
        b"\xff\xd8\xff\xe0\x00\x04\x00\x00"
        + b"\xff\xc0\x00\x0b\x08"
        + struct.pack(">HH", height, width)
        + b"\x01\x01\x11\x00"
    )


def test_decompression_bombs_are_refused_by_header() -> None:
    from app.modules.faces.domain.image import check_image

    for bomb in (
        _png_header(30000, 10),
        _png_header(6000, 6000),
        _jpeg_header(9000, 100),
        _jpeg_header(5001, 5000),
    ):
        mime = "image/png" if bomb[1:4] == b"PNG" else "image/jpeg"
        with pytest.raises(FaceImageTooLargeError):
            check_image(bomb, mime)
    check_image(_png_header(4000, 4000), "image/png")
    check_image(_jpeg_header(1920, 1080), "image/jpeg")

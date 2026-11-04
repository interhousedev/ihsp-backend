"""ADM-PHOTO-2: the admin exports the photos of a group as one ZIP archive."""

import dataclasses
import io
import uuid
import zipfile

from app.modules.academic.domain.schedule.errors import GroupNotFoundError
from app.shared.actor import Role
from app.shared.base_error import ForbiddenError
from app.shared.ids import new_id
from tests.academic.schedule.env import Env
from tests.factories import make_actor

import pytest

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-bytes"
PNG = b"\x89PNG\r\n\x1a\n" + b"png-bytes"
MANIFEST = "manifest.txt"


def _with_photo(env: Env, user_id: object, data: bytes) -> None:
    user = env.identity.users[user_id]  # type: ignore[index]
    file_id = env.files.add(data)
    env.identity.add(dataclasses.replace(user, photo_file_id=file_id))


def _read(archive: object) -> zipfile.ZipFile:
    archive.fp.seek(0)  # type: ignore[attr-defined]
    return zipfile.ZipFile(io.BytesIO(archive.fp.read()))  # type: ignore[attr-defined]


async def test_each_student_photo_is_stored_under_the_full_name(env: Env) -> None:
    """ADM-PHOTO-2: Ivanov Ivan Ivanovich.jpg, and the bytes are the photo."""
    group = await env.group("2TN2")
    ivan = await env.student(
        group, first_name="Ivan", last_name="Ivanov", middle_name="Ivanovich"
    )
    aziza = await env.student(group, first_name="Aziza", last_name="Karimova")
    _with_photo(env, ivan.id, JPEG)
    _with_photo(env, aziza.id, PNG)

    archive = await env.services.export_group_photos.execute(
        make_actor(Role.ADMIN), group.id
    )
    names = _read(archive).namelist()

    assert "Ivanov Ivan Ivanovich.jpg" in names
    assert "Karimova Aziza.png" in names
    assert _read(archive).read("Ivanov Ivan Ivanovich.jpg") == JPEG
    assert _read(archive).read("Karimova Aziza.png") == PNG


async def test_students_without_a_photo_are_listed_in_the_manifest(env: Env) -> None:
    """ADM-PHOTO-2: a student with no photo is reported, not silently skipped."""
    group = await env.group("2TN2")
    ivan = await env.student(group, first_name="Ivan", last_name="Ivanov")
    await env.student(group, first_name="Petr", last_name="Petrov")
    _with_photo(env, ivan.id, JPEG)

    archive = await env.services.export_group_photos.execute(
        make_actor(Role.ADMIN), group.id
    )
    manifest = _read(archive).read(MANIFEST).decode("utf-8")

    assert archive.exported == 1
    assert archive.missing == ("Petrov Petr",)
    assert "Petrov Petr" in manifest
    assert "Ivanov Ivan" not in manifest


async def test_a_photo_that_is_not_an_image_or_is_gone_counts_as_missing(
    env: Env,
) -> None:
    """ADM-PHOTO-2: a lost file or non-image bytes never break the whole export."""
    group = await env.group("2TN2")
    gone = await env.student(group, first_name="Gone", last_name="Lost")
    text = await env.student(group, first_name="Text", last_name="Only")
    env.identity.add(
        dataclasses.replace(env.identity.users[gone.id], photo_file_id=new_id())
    )
    _with_photo(env, text.id, b"<html>not a photo</html>")

    archive = await env.services.export_group_photos.execute(
        make_actor(Role.ADMIN), group.id
    )

    assert archive.exported == 0
    assert sorted(archive.missing) == ["Lost Gone", "Only Text"]


async def test_a_left_student_is_not_exported(env: Env) -> None:
    """ADM-PHOTO-2: only students who are in the group now."""
    group = await env.group("2TN2")
    left = await env.student(
        group, first_name="Left", last_name="Earlier", status="left"
    )
    _with_photo(env, left.id, JPEG)

    archive = await env.services.export_group_photos.execute(
        make_actor(Role.ADMIN), group.id
    )

    assert archive.exported == 0
    assert archive.missing == ()


async def test_two_students_with_one_name_both_keep_their_photo(env: Env) -> None:
    """ADM-PHOTO-2: duplicates get a numeric suffix instead of overwriting."""
    group = await env.group("2TN2")
    first = await env.student(group, first_name="Ivan", last_name="Ivanov")
    second = await env.student(group, first_name="Ivan", last_name="Ivanov")
    _with_photo(env, first.id, JPEG)
    _with_photo(env, second.id, JPEG)

    archive = await env.services.export_group_photos.execute(
        make_actor(Role.ADMIN), group.id
    )
    names = _read(archive).namelist()

    assert "Ivanov Ivan.jpg" in names
    assert "Ivanov Ivan (2).jpg" in names


async def test_the_archive_names_are_utf8_flagged(env: Env) -> None:
    """ADM-PHOTO-2: non-ASCII names carry the UTF-8 flag (bit 11)."""
    group = await env.group("2TN2")
    user = await env.student(group, first_name="Ўткир", last_name="Қодиров")
    _with_photo(env, user.id, JPEG)

    archive = await env.services.export_group_photos.execute(
        make_actor(Role.ADMIN), group.id
    )
    info = _read(archive).getinfo("Қодиров Ўткир.jpg")

    assert info.flag_bits & 0x800


async def test_the_export_is_audited_with_its_counts(env: Env) -> None:
    """ADM-PHOTO-2: who exported which group, how many photos and how many missing."""
    group = await env.group("2TN2")
    ivan = await env.student(group, first_name="Ivan", last_name="Ivanov")
    await env.student(group, first_name="Petr", last_name="Petrov")
    _with_photo(env, ivan.id, JPEG)
    admin = make_actor(Role.ADMIN)

    await env.services.export_group_photos.execute(admin, group.id)

    (draft,) = [a for a in env.audits if a.type == "group.photos_exported"]
    assert draft.actor_id == admin.user_id
    assert draft.metadata == {"group_id": str(group.id), "exported": 1, "missing": 1}


@pytest.mark.parametrize("role", [Role.TEACHER, Role.STUDENT, Role.LIBRARIAN])
async def test_only_an_administrator_may_export(env: Env, role: Role) -> None:
    """ADM-PHOTO-2: the same rule as the admin user management, not the curator's."""
    group = await env.group("2TN2")

    with pytest.raises(ForbiddenError):
        await env.services.export_group_photos.execute(make_actor(role), group.id)


async def test_an_unknown_group_is_not_found(env: Env) -> None:
    """ADM-PHOTO-2: a missing group answers not found."""
    with pytest.raises(GroupNotFoundError):
        await env.services.export_group_photos.execute(
            make_actor(Role.ADMIN), uuid.uuid4()
        )

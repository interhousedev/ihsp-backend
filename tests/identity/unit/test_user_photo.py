"""Profile photos: validation rules, setting, removing and the directory links."""

from uuid import UUID

from app.modules.identity.domain.errors import (
    PhotoEmptyError,
    PhotoTooLargeError,
    PhotoTypeNotAllowedError,
    UserNotFoundError,
)
from app.modules.identity.domain.photo import (
    JPEG,
    MAX_PHOTO_BYTES,
    PNG,
    check_photo,
)
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from app.shared.ids import new_id
from tests.identity.support import World

import pytest

PNG_HEADER = b"\x89PNG\r\n\x1a\n"
JPEG_HEADER = b"\xff\xd8\xff\xe0"


def png(size: int = 64) -> bytes:
    """A payload that starts like a PNG file."""
    return PNG_HEADER + b"\x00" * (size - len(PNG_HEADER))


def jpeg(size: int = 64) -> bytes:
    """A payload that starts like a JPEG file."""
    return JPEG_HEADER + b"\x00" * (size - len(JPEG_HEADER))


# - - - The pure rules - - -


def test_a_png_is_accepted() -> None:
    assert check_photo(png()) == PNG
    assert (PNG.extension, PNG.content_type) == ("png", "image/png")


def test_a_jpeg_is_accepted() -> None:
    assert check_photo(jpeg()) == JPEG
    assert (JPEG.extension, JPEG.content_type) == ("jpg", "image/jpeg")


def test_the_limit_is_five_mebibytes_and_the_last_byte_counts() -> None:
    assert MAX_PHOTO_BYTES == 5 * 1024 * 1024

    assert check_photo(png(MAX_PHOTO_BYTES)) == PNG
    assert check_photo(jpeg(MAX_PHOTO_BYTES)) == JPEG
    with pytest.raises(PhotoTooLargeError) as exc:
        check_photo(png(MAX_PHOTO_BYTES + 1))
    assert exc.value.status == 413
    assert exc.value.params == {"max_mb": 5}


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(PhotoEmptyError) as exc:
        check_photo(b"")
    assert exc.value.status == 422


@pytest.mark.parametrize(
    "data",
    [
        b"GIF89a" + b"\x00" * 32,
        b"%PDF-1.7\n" + b"\x00" * 32,
        b"just some text, not a picture",
        b"RIFF\x00\x00\x00\x00WEBPVP8 ",
        b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
        b"\x89PNG",  # a truncated signature
        b"\xff\xd8",  # a truncated signature
        b"\x00" + PNG_HEADER,  # the signature is not at the start
    ],
    ids=["gif", "pdf", "text", "webp", "svg", "short-png", "short-jpeg", "shifted"],
)
def test_other_content_is_refused(data: bytes) -> None:
    with pytest.raises(PhotoTypeNotAllowedError) as exc:
        check_photo(data)
    assert exc.value.status == 422
    assert exc.value.code == "id/photo-type-not-allowed"


def test_only_the_content_decides_not_a_name_or_a_declared_type() -> None:
    """``check_photo`` gets nothing but bytes: a "photo.gif" holding a PNG is a PNG."""
    assert check_photo(png()).extension == "png"
    assert check_photo(jpeg()).extension == "jpg"


# - - - Setting and removing - - -


async def file_of(world: World, file_id: UUID | None) -> FileRef | None:
    """The stored file behind an id, or None when it is gone."""
    assert file_id is not None
    return await world.files.services.public.get(file_id)


async def test_setting_a_photo_stores_a_staff_file_and_returns_a_link(
    auth_world: World,
) -> None:
    teacher = await auth_world.add_user()

    url = await auth_world.auth.set_user_photo.execute(teacher.id, png())

    ref = await file_of(auth_world, auth_world.user(teacher.id).photo_file_id)
    assert ref is not None
    assert (ref.owner_id, ref.scope, ref.purpose) == (
        teacher.id,
        FileScope.STAFF,
        FilePurpose.USER_PHOTO,
    )
    assert (ref.name, ref.content_type, ref.byte_size) == (
        "photo.png",
        "image/png",
        64,
    )
    assert url is not None and "inline" in url and "expires=3600" in url


async def test_a_jpeg_is_stored_as_photo_jpg(auth_world: World) -> None:
    teacher = await auth_world.add_user()

    await auth_world.auth.set_user_photo.execute(teacher.id, jpeg())

    ref = await file_of(auth_world, auth_world.user(teacher.id).photo_file_id)
    assert ref is not None and (ref.name, ref.content_type) == (
        "photo.jpg",
        "image/jpeg",
    )


async def test_a_new_photo_replaces_and_deletes_the_old_one(auth_world: World) -> None:
    teacher = await auth_world.add_user()
    await auth_world.auth.set_user_photo.execute(teacher.id, png())
    first = auth_world.user(teacher.id).photo_file_id

    await auth_world.auth.set_user_photo.execute(teacher.id, jpeg())

    second = auth_world.user(teacher.id).photo_file_id
    assert second is not None and second != first
    assert await file_of(auth_world, first) is None
    assert await file_of(auth_world, second) is not None


async def test_a_refused_photo_changes_nothing(auth_world: World) -> None:
    teacher = await auth_world.add_user()
    await auth_world.auth.set_user_photo.execute(teacher.id, png())
    before = auth_world.user(teacher.id).photo_file_id

    for bad, error in (
        (b"", PhotoEmptyError),
        (b"GIF89a....", PhotoTypeNotAllowedError),
        (png(MAX_PHOTO_BYTES + 1), PhotoTooLargeError),
    ):
        with pytest.raises(error):
            await auth_world.auth.set_user_photo.execute(teacher.id, bad)

    assert auth_world.user(teacher.id).photo_file_id == before
    assert await file_of(auth_world, before) is not None


async def test_an_unknown_user_gets_no_file(auth_world: World) -> None:
    with pytest.raises(UserNotFoundError):
        await auth_world.auth.set_user_photo.execute(new_id(), png())
    with pytest.raises(UserNotFoundError):
        await auth_world.auth.remove_user_photo.execute(new_id())

    assert auth_world.files.db.all_rows() == []
    assert auth_world.files.storage.objects == {}


async def test_removing_clears_the_link_and_deletes_the_file(
    auth_world: World,
) -> None:
    teacher = await auth_world.add_user()
    await auth_world.auth.set_user_photo.execute(teacher.id, png())
    stored = auth_world.user(teacher.id).photo_file_id

    await auth_world.auth.remove_user_photo.execute(teacher.id)

    assert auth_world.user(teacher.id).photo_file_id is None
    assert await file_of(auth_world, stored) is None


async def test_removing_twice_or_without_a_photo_is_fine(auth_world: World) -> None:
    teacher = await auth_world.add_user()

    await auth_world.auth.remove_user_photo.execute(teacher.id)
    await auth_world.auth.set_user_photo.execute(teacher.id, png())
    await auth_world.auth.remove_user_photo.execute(teacher.id)
    await auth_world.auth.remove_user_photo.execute(teacher.id)

    assert auth_world.user(teacher.id).photo_file_id is None


# - - - The directory - - -


async def test_the_user_ref_carries_the_photo_file_id(auth_world: World) -> None:
    teacher = await auth_world.add_user()
    directory = auth_world.auth.directory
    before = await directory.get_user(teacher.id)

    await auth_world.auth.set_user_photo.execute(teacher.id, png())

    after = await directory.get_user(teacher.id)
    assert before is not None and before.photo_file_id is None
    assert after is not None and after.photo_file_id is not None
    assert after.photo_file_id == auth_world.user(teacher.id).photo_file_id


async def test_photo_urls_list_only_users_with_a_photo(auth_world: World) -> None:
    with_photo = await auth_world.add_user(login="with.photo")
    without = await auth_world.add_user(login="no.photo", recovery_email="n@x.org")
    await auth_world.auth.set_user_photo.execute(with_photo.id, png())
    directory = auth_world.auth.directory

    urls = await directory.photo_urls([with_photo.id, without.id, new_id()])

    assert set(urls) == {with_photo.id}
    assert "inline" in urls[with_photo.id] and "expires=3600" in urls[with_photo.id]
    assert await directory.photo_urls([]) == {}
    assert await directory.photo_urls([without.id]) == {}


async def test_a_lost_file_leaves_the_user_out_instead_of_failing(
    auth_world: World,
) -> None:
    gone = await auth_world.add_user(login="gone.photo")
    kept = await auth_world.add_user(login="kept.photo", recovery_email="k@x.org")
    await auth_world.auth.set_user_photo.execute(gone.id, png())
    await auth_world.auth.set_user_photo.execute(kept.id, png())
    lost = auth_world.user(gone.id).photo_file_id
    assert lost is not None
    await auth_world.files.services.public.delete_file(lost)

    urls = await auth_world.auth.directory.photo_urls([gone.id, kept.id])

    assert set(urls) == {kept.id}

"""LIB-3, LIB-5 (files part): who may open a library file through the files module."""

from collections.abc import Callable
from uuid import UUID

from app.modules.files.domain.errors import StoredFileNotFoundError
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose
from tests.fakes.files.services import FilesFakes
from tests.files.helpers import PDF_TYPE, make_pdf, upload_ready

import pytest


async def _library_file(
    fakes: FilesFakes,
    owner: Actor,
    purpose: FilePurpose = FilePurpose.LIBRARY_MATERIAL,
) -> UUID:
    return await upload_ready(
        fakes,
        owner,
        name="notes.pdf",
        data=make_pdf("Newton's laws"),
        content_type=PDF_TYPE,
        purpose=purpose,
    )


async def test_the_owner_gets_a_url_for_their_own_library_file(
    fakes: FilesFakes, student: Actor
) -> None:
    """LIB-5: the uploader can still open what they uploaded."""
    file_id = await _library_file(fakes, student)

    result = await fakes.services.get_download_url.execute(student, file_id)

    assert result.url.startswith("memory://")


@pytest.mark.parametrize("roles", [(Role.STUDENT, Role.LIBRARIAN), (Role.ADMIN,)])
async def test_librarians_and_administrators_get_urls_for_any_library_file(
    fakes: FilesFakes,
    student: Actor,
    make_actor: Callable[..., Actor],
    roles: tuple[Role, ...],
) -> None:
    """LIB-3: librarian or admin (the moderators) read what was uploaded."""
    file_id = await _library_file(fakes, student)

    result = await fakes.services.get_download_url.execute(make_actor(*roles), file_id)
    shown = await fakes.services.get_file.execute(make_actor(*roles), file_id)

    assert result.url.startswith("memory://")
    assert shown.file.id == file_id


@pytest.mark.parametrize("role", [Role.STUDENT, Role.TEACHER, Role.LMS_ADMIN])
async def test_everyone_else_gets_404_from_the_generic_endpoints(
    fakes: FilesFakes,
    student: Actor,
    make_actor: Callable[..., Actor],
    role: Role,
) -> None:
    """LIB-3: the library serves other readers through its own endpoints."""
    file_id = await _library_file(fakes, student)
    stranger = make_actor(role)

    with pytest.raises(StoredFileNotFoundError) as url_error:
        await fakes.services.get_download_url.execute(stranger, file_id)
    with pytest.raises(StoredFileNotFoundError):
        await fakes.services.get_file.execute(stranger, file_id)

    assert url_error.value.status == 404


async def test_a_librarian_does_not_gain_access_to_ordinary_files(
    fakes: FilesFakes, student: Actor, librarian: Actor
) -> None:
    """The librarian role opens library files only, never a student's My files."""
    private = await upload_ready(
        fakes,
        student,
        name="diary.pdf",
        data=make_pdf("private"),
        content_type=PDF_TYPE,
    )

    with pytest.raises(StoredFileNotFoundError):
        await fakes.services.get_download_url.execute(librarian, private)
    assert not await fakes.services.public.check_access(private, librarian)


@pytest.mark.parametrize(
    ("roles", "allowed"),
    [
        ((Role.STUDENT,), False),
        ((Role.TEACHER,), False),
        ((Role.STUDENT, Role.LIBRARIAN), True),
        ((Role.ADMIN,), True),
    ],
)
async def test_check_access_follows_the_same_rule(
    fakes: FilesFakes,
    student: Actor,
    make_actor: Callable[..., Actor],
    roles: tuple[Role, ...],
    allowed: bool,
) -> None:
    """The FilesApi answer matches the HTTP answer for library files."""
    file_id = await _library_file(fakes, student)

    assert await fakes.services.public.check_access(file_id, make_actor(*roles)) is (
        allowed
    )
    assert await fakes.services.public.check_access(file_id, student)


async def test_the_files_api_gives_a_url_with_a_longer_life_for_the_reader(
    fakes: FilesFakes, student: Actor
) -> None:
    """LIB-6: the reader asks for 900 seconds instead of the usual 60."""
    file_id = await _library_file(fakes, student)

    default = await fakes.services.public.download_url(file_id)
    reader = await fakes.services.public.download_url(file_id, ttl_seconds=900)

    assert "expires=60" in default
    assert "expires=900" in reader


@pytest.mark.parametrize(("asked", "signed"), [(0, 1), (-5, 1), (10**6, 3600)])
async def test_an_absurd_url_life_is_clamped(
    fakes: FilesFakes, student: Actor, asked: int, signed: int
) -> None:
    """One second at least, one hour at most."""
    file_id = await _library_file(fakes, student)

    url = await fakes.services.public.download_url(file_id, ttl_seconds=asked)

    assert f"expires={signed}" in url

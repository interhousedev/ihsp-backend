"""LIB-3, LIB-5 (files part): the `library` scope, its purposes, limits and quotas."""

from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

from app.modules.files.application.request_upload import UploadTicket
from app.modules.files.domain.errors import (
    FileTooLargeError,
    QuotaExceededError,
    TypeNotAllowedError,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.contracts.files import FilePurpose, FileScope
from tests.fakes.clock import FixedClock
from tests.fakes.files.services import DEFAULT_LIMITS, FilesFakes, build_files_fakes
from tests.fakes.tasks import FakeTaskKicker
from tests.files.helpers import PDF_TYPE, make_pdf, sha256_b64

import pytest

PDF = b"%PDF-1.4 tiny"
BOOK = FilePurpose.LIBRARY_BOOK
COVER = FilePurpose.LIBRARY_COVER
MATERIAL = FilePurpose.LIBRARY_MATERIAL


async def ask(
    fakes: FilesFakes,
    actor: Actor,
    purpose: FilePurpose,
    *,
    name: str = "book.pdf",
    data: bytes = PDF,
    size: int | None = None,
    content_type: str = PDF_TYPE,
) -> UploadTicket:
    """Call request_upload with the defaults of a small PDF."""
    return await fakes.services.request_upload.execute(
        actor,
        name=name,
        size=len(data) if size is None else size,
        content_type=content_type,
        sha256_b64=sha256_b64(data),
        purpose=purpose,
    )


def test_the_library_scope_and_purposes_have_stable_values() -> None:
    """LIB-3: the strings are stored in the database and sent to the web client."""
    assert FileScope.LIBRARY.value == "library"
    assert BOOK.value == "library_book"
    assert COVER.value == "library_cover"
    assert MATERIAL.value == "library_material"


async def test_a_librarians_book_goes_to_the_library_scope_without_a_term(
    fakes: FilesFakes, librarian: Actor
) -> None:
    """LIB-3: scope follows the purpose; the key is `library/yyyy-mm/{id}.pdf`."""
    fakes.terms.current = uuid4()

    ticket = await ask(fakes, librarian, BOOK)

    file = fakes.db.row(ticket.view.file.id)
    assert file.scope == FileScope.LIBRARY
    assert file.purpose == BOOK
    assert file.term_id is None
    assert file.expires_at is None
    assert file.key == f"library/2026-10/{file.id}.pdf"
    assert ticket.view.expires_on is None


@pytest.mark.parametrize("purpose", [BOOK, COVER, MATERIAL])
async def test_an_administrator_may_upload_every_library_purpose(
    fakes: FilesFakes, admin: Actor, purpose: FilePurpose
) -> None:
    """LIB-3: Administration can do whatever a librarian can."""
    ticket = await ask(fakes, admin, purpose, name="x.pdf")

    assert fakes.db.row(ticket.view.file.id).scope == FileScope.LIBRARY


@pytest.mark.parametrize("role", [Role.STUDENT, Role.TEACHER])
@pytest.mark.parametrize("purpose", [BOOK, COVER])
async def test_books_and_covers_are_for_librarians_and_administrators_only(
    fakes: FilesFakes,
    make_actor: Callable[..., Actor],
    role: Role,
    purpose: FilePurpose,
) -> None:
    """LIB-3: others get the usual forbidden error and nothing is stored."""
    actor = make_actor(role)

    with pytest.raises(ForbiddenError):
        await ask(fakes, actor, purpose)

    assert fakes.db.all_rows() == []


@pytest.mark.parametrize("role", [Role.STUDENT, Role.TEACHER, Role.LIBRARIAN])
async def test_everybody_may_upload_materials(
    fakes: FilesFakes, make_actor: Callable[..., Actor], role: Role
) -> None:
    """LIB-5: students, teachers and librarians upload materials (scope library)."""
    actor = make_actor(role)

    ticket = await ask(fakes, actor, MATERIAL, name="notes.pdf")

    file = fakes.db.row(ticket.view.file.id)
    assert (file.scope, file.purpose) == (FileScope.LIBRARY, MATERIAL)
    assert file.owner_id == actor.user_id


async def test_the_library_ceiling_replaces_the_normal_file_limit(
    clock: FixedClock, kicker: FakeTaskKicker, librarian: Actor, student: Actor
) -> None:
    """LIB-3: 300 MB per book file, while ordinary files keep their 100 MB."""
    limits = replace(DEFAULT_LIMITS, file_max_bytes=10, library_file_max_bytes=100)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    await ask(fakes, librarian, BOOK, size=100)

    with pytest.raises(FileTooLargeError) as library_error:
        await ask(fakes, librarian, BOOK, size=101)
    with pytest.raises(FileTooLargeError):
        await ask(fakes, student, FilePurpose.LINK, size=11)

    assert library_error.value.params["max_bytes"] == 100


async def test_epub_books_are_accepted(fakes: FilesFakes, librarian: Actor) -> None:
    """LIB-3: `.epub` is a zip-based type with its own content type."""
    ticket = await ask(
        fakes,
        librarian,
        BOOK,
        name="Book.EPUB",
        content_type="application/epub+zip",
    )

    file = fakes.db.row(ticket.view.file.id)
    assert file.content_type == "application/epub+zip"
    assert file.key.endswith(".epub")


async def test_a_student_materials_use_a_quota_of_their_own(
    clock: FixedClock, kicker: FakeTaskKicker, student: Actor
) -> None:
    """LIB-5: LIBRARY__STUDENT_QUOTA_BYTES, counted over the library scope."""
    limits = replace(DEFAULT_LIMITS, library_student_quota_bytes=10)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    await ask(fakes, student, MATERIAL, data=b"1234567890")

    with pytest.raises(QuotaExceededError) as caught:
        await ask(fakes, student, MATERIAL, data=b"x")

    assert caught.value.params["quota_bytes"] == 10


async def test_a_teachers_materials_use_the_larger_teacher_quota(
    clock: FixedClock, kicker: FakeTaskKicker, teacher: Actor
) -> None:
    """LIB-5: LIBRARY__TEACHER_QUOTA_BYTES (2 GB by default)."""
    limits = replace(
        DEFAULT_LIMITS, library_student_quota_bytes=1, library_teacher_quota_bytes=20
    )
    fakes = build_files_fakes(clock, kicker, limits=limits)
    await ask(fakes, teacher, MATERIAL, data=b"1234567890")
    await ask(fakes, teacher, MATERIAL, data=b"1234567890")

    with pytest.raises(QuotaExceededError):
        await ask(fakes, teacher, MATERIAL, data=b"x")


@pytest.mark.parametrize("roles", [(Role.STUDENT, Role.LIBRARIAN), (Role.ADMIN,)])
async def test_librarians_and_administrators_have_no_library_quota(
    clock: FixedClock,
    kicker: FakeTaskKicker,
    make_actor: Callable[..., Actor],
    roles: tuple[Role, ...],
) -> None:
    """LIB-3: a librarian can fill the shelves, however much it takes."""
    limits = replace(
        DEFAULT_LIMITS, library_student_quota_bytes=1, library_teacher_quota_bytes=1
    )
    fakes = build_files_fakes(clock, kicker, limits=limits)
    actor = make_actor(*roles)

    for purpose in (BOOK, BOOK, MATERIAL, COVER):
        await ask(fakes, actor, purpose, data=b"1234567890")


async def test_library_files_do_not_use_up_the_normal_student_quota(
    clock: FixedClock, kicker: FakeTaskKicker, student: Actor
) -> None:
    """FILE-5 stays separate: a full library quota leaves My files untouched."""
    limits = replace(
        DEFAULT_LIMITS, student_quota_bytes=10, library_student_quota_bytes=10
    )
    fakes = build_files_fakes(clock, kicker, limits=limits)
    await ask(fakes, student, MATERIAL, data=b"1234567890")

    await ask(fakes, student, FilePurpose.LINK, data=b"1234567890")


async def test_normal_files_do_not_use_up_the_library_quota(
    clock: FixedClock, kicker: FakeTaskKicker, student: Actor
) -> None:
    """The other way round: a full term quota does not block a material."""
    limits = replace(
        DEFAULT_LIMITS, student_quota_bytes=10, library_student_quota_bytes=10
    )
    fakes = build_files_fakes(clock, kicker, limits=limits)
    await ask(fakes, student, FilePurpose.LINK, data=b"1234567890")

    await ask(fakes, student, MATERIAL, data=b"1234567890")


async def test_server_side_library_files_check_the_scope_and_purpose_pair(
    fakes: FilesFakes,
) -> None:
    """A `library_*` purpose only lives in the library scope, and the reverse."""
    for scope, purpose in (
        (FileScope.STAFF, BOOK),
        (FileScope.STUDENT, MATERIAL),
        (FileScope.LIBRARY, FilePurpose.LINK),
    ):
        with pytest.raises(TypeNotAllowedError):
            await fakes.services.public.store_bytes(
                owner_id=uuid4(),
                scope=scope,
                purpose=purpose,
                name="a.pdf",
                data=make_pdf("x"),
            )

    assert fakes.db.all_rows() == []


async def test_server_side_library_files_obey_the_library_ceiling(
    clock: FixedClock, kicker: FakeTaskKicker
) -> None:
    """The scope ceiling holds for bytes stored by the server too."""
    limits = replace(DEFAULT_LIMITS, file_max_bytes=10, library_file_max_bytes=10_000)
    fakes = build_files_fakes(clock, kicker, limits=limits)
    data = make_pdf("A page of text")
    assert 10 < len(data) < 10_000

    ref = await fakes.services.public.store_bytes(
        owner_id=uuid4(),
        scope=FileScope.LIBRARY,
        purpose=MATERIAL,
        name="a.pdf",
        data=data,
    )

    assert ref.scope == FileScope.LIBRARY
    assert fakes.db.row(ref.id).key.startswith("library/2026-10/")

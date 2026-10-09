"""LIB-2, LIB-14: book suggestions and Administration's sanctions."""

from datetime import timedelta
from uuid import UUID

from app.modules.library.application.materials.inputs import MaterialData
from app.modules.library.domain.enums import SanctionKind, SuggestionStatus
from app.modules.library.domain.errors import (
    InvalidTransitionError,
    SuggestionNotFoundError,
    UploadBannedError,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError, ValidationFailedError
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft
from tests.fakes.clock import FixedClock
from tests.fakes.library.material_files import MaterialFilesApi

import pytest

# - - - Suggestions - - -


async def test_a_suggestion_waits_in_the_queue(
    library: LibraryServices,
    student: Actor,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """LIB-2: a student suggests a book by title, link and note."""
    await library.materials.create_suggestion.execute(
        student,
        title=" Atom physics workbook ",
        url="https://example.org/atom",
        file_id=None,
        note="For the olympiad group",
    )

    async with uow_factory() as uow:
        (stored,) = await uow.moderation.new_suggestions(limit=10, offset=0)
    assert stored.user_id == student.user_id
    assert stored.title == "Atom physics workbook"
    assert stored.url == "https://example.org/atom"
    assert stored.note == "For the olympiad group"
    assert stored.status is SuggestionStatus.NEW
    assert stored.created_at == clock.now()


async def test_a_suggestion_may_carry_the_uploaded_file(
    library: LibraryServices,
    teacher: Actor,
    files_api: MaterialFilesApi,
    uow_factory: UowFactory,
) -> None:
    """LIB-2: a teacher suggests a book by uploading it."""
    file_id = files_api.upload(teacher.user_id, name="book.pdf")

    await library.materials.create_suggestion.execute(
        teacher, title="Optics", url=None, file_id=file_id, note=None
    )

    async with uow_factory() as uow:
        (stored,) = await uow.moderation.new_suggestions(limit=10, offset=0)
    assert stored.file_id == file_id


@pytest.mark.parametrize(
    ("title", "url", "note", "field"),
    [
        ("  ", None, None, "title"),
        ("x" * 256, None, None, "title"),
        ("Book", "javascript:alert(1)", None, "url"),
        ("Book", "ftp://example.org/x", None, "url"),
        ("Book", None, "x" * 1001, "note"),
    ],
)
async def test_bad_suggestions_are_refused(
    library: LibraryServices,
    student: Actor,
    title: str,
    url: str | None,
    note: str | None,
    field: str,
) -> None:
    """LIB-2: titles, links and notes are checked."""
    with pytest.raises(ValidationFailedError) as caught:
        await library.materials.create_suggestion.execute(
            student, title=title, url=url, file_id=None, note=note
        )

    assert caught.value.params == {"field": field}


async def test_an_unknown_file_cannot_be_suggested(
    library: LibraryServices, student: Actor
) -> None:
    """LIB-2: the file must exist."""
    with pytest.raises(ValidationFailedError) as caught:
        await library.materials.create_suggestion.execute(
            student, title="Book", url=None, file_id=new_id(), note=None
        )

    assert caught.value.params == {"field": "file_id"}


async def test_someone_elses_file_cannot_be_suggested(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    files_api: MaterialFilesApi,
) -> None:
    """LIB-2: file ids come from the client."""
    file_id = files_api.upload(other_student.user_id)

    with pytest.raises(ValidationFailedError):
        await library.materials.create_suggestion.execute(
            student, title="Book", url=None, file_id=file_id, note=None
        )


@pytest.mark.parametrize(
    ("accept", "expected"),
    [(True, SuggestionStatus.ACCEPTED), (False, SuggestionStatus.DECLINED)],
)
async def test_a_librarian_accepts_or_declines_a_suggestion(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    uow_factory: UowFactory,
    audit_log: list[AuditDraft],
    accept: bool,
    expected: SuggestionStatus,
) -> None:
    """LIB-2: the decision leaves the queue and is audited."""
    await library.materials.create_suggestion.execute(
        student, title="Book", url=None, file_id=None, note=None
    )
    async with uow_factory() as uow:
        (stored,) = await uow.moderation.new_suggestions(limit=10, offset=0)

    await library.materials.decide_suggestion.execute(
        other_librarian, stored.id, accept=accept
    )

    async with uow_factory() as uow:
        decided = await uow.moderation.get_suggestion(stored.id)
        assert await uow.moderation.new_suggestions(limit=10, offset=0) == []
    assert decided is not None
    assert (decided.status, decided.handled_by) == (expected, other_librarian.user_id)
    assert audit_log[-1].type == "library.suggestion"
    assert audit_log[-1].actor_id == other_librarian.user_id


async def test_a_suggestion_is_decided_once(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    uow_factory: UowFactory,
) -> None:
    """LIB-2: deciding twice is refused."""
    await library.materials.create_suggestion.execute(
        student, title="Book", url=None, file_id=None, note=None
    )
    async with uow_factory() as uow:
        (stored,) = await uow.moderation.new_suggestions(limit=10, offset=0)
    await library.materials.decide_suggestion.execute(
        other_librarian, stored.id, accept=True
    )

    with pytest.raises(InvalidTransitionError):
        await library.materials.decide_suggestion.execute(
            other_librarian, stored.id, accept=False
        )


async def test_only_librarians_decide_and_unknown_suggestions_are_missing(
    library: LibraryServices, student: Actor, other_librarian: Actor
) -> None:
    """LIB-2: students cannot decide; `404` for an unknown id."""
    with pytest.raises(ForbiddenError):
        await library.materials.decide_suggestion.execute(
            student, new_id(), accept=True
        )
    with pytest.raises(SuggestionNotFoundError):
        await library.materials.decide_suggestion.execute(
            other_librarian, new_id(), accept=True
        )


# - - - Sanctions - - -


async def test_an_admin_bans_a_user_until_a_date_and_it_is_audited(
    library: LibraryServices,
    student: Actor,
    admin: Actor,
    clock: FixedClock,
    audit_log: list[AuditDraft],
) -> None:
    """LIB-14: the ban has an end date and an audit event."""
    until = clock.now() + timedelta(days=7)

    sanction = await library.materials.create_sanction.execute(
        admin,
        user_id=student.user_id,
        kind=SanctionKind.UPLOAD_BAN,
        until=until,
        reason="repeated copyright reports",
    )

    assert sanction.user_id == student.user_id
    assert (sanction.kind, sanction.until) == (SanctionKind.UPLOAD_BAN, until)
    assert sanction.set_by == admin.user_id
    assert sanction.created_at == clock.now()
    assert audit_log[-1].type == "library.sanction"
    assert audit_log[-1].user_id == student.user_id
    assert audit_log[-1].actor_id == admin.user_id
    assert audit_log[-1].metadata == {
        "sanction_id": str(sanction.id),
        "kind": "upload_ban",
        "until": until.isoformat(),
        "reason": "repeated copyright reports",
    }


async def test_a_banned_user_cannot_create_a_material_until_it_ends(
    library: LibraryServices,
    student: Actor,
    admin: Actor,
    material_data: MaterialData,
    clock: FixedClock,
) -> None:
    """LIB-14: the ban blocks uploads and lifts by the clock."""
    until = clock.now() + timedelta(days=1)
    await library.materials.create_sanction.execute(
        admin,
        user_id=student.user_id,
        kind=SanctionKind.UPLOAD_BAN,
        until=until,
        reason="spam",
    )

    with pytest.raises(UploadBannedError):
        await library.materials.create_material.execute(
            student, material_data, locale="en"
        )
    clock.advance(days=1, minutes=1)

    view = await library.materials.create_material.execute(
        student, material_data, locale="en"
    )
    assert view.card.id is not None


async def test_a_warning_does_not_block_and_ignores_an_end_date(
    library: LibraryServices,
    student: Actor,
    admin: Actor,
    clock: FixedClock,
    material_data: MaterialData,
) -> None:
    """LIB-14: warnings are records only."""
    sanction = await library.materials.create_sanction.execute(
        admin,
        user_id=student.user_id,
        kind=SanctionKind.WARNING,
        until=clock.now() + timedelta(days=3),
        reason="please read the content policy",
    )

    assert sanction.until is None
    view = await library.materials.create_material.execute(
        student, material_data, locale="en"
    )
    assert view.card.id is not None


@pytest.mark.parametrize("problem", ["reason", "until", "user_id"])
async def test_bad_sanctions_are_refused(
    library: LibraryServices,
    student: Actor,
    admin: Actor,
    clock: FixedClock,
    problem: str,
) -> None:
    """LIB-14: a reason, a future end date and a known user are required."""
    user_id = new_id() if problem == "user_id" else student.user_id
    reason = "  " if problem == "reason" else "spam"
    until = clock.now() - timedelta(hours=1) if problem == "until" else None

    with pytest.raises(ValidationFailedError) as caught:
        await library.materials.create_sanction.execute(
            admin,
            user_id=user_id,
            kind=SanctionKind.UPLOAD_BAN,
            until=until,
            reason=reason,
        )

    assert caught.value.params == {"field": problem}


async def test_only_administration_sets_and_reads_sanctions(
    library: LibraryServices,
    student: Actor,
    other_librarian: Actor,
    teacher: Actor,
) -> None:
    """LIB-14: librarians cannot ban; sanctions are Administration's."""
    for actor in (other_librarian, teacher, student):
        with pytest.raises(ForbiddenError):
            await library.materials.create_sanction.execute(
                actor,
                user_id=student.user_id,
                kind=SanctionKind.WARNING,
                until=None,
                reason="x",
            )
        with pytest.raises(ForbiddenError):
            await library.materials.list_sanctions.execute(actor, user_id=None)


async def test_sanctions_are_listed_newest_first_per_user(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    admin: Actor,
    clock: FixedClock,
) -> None:
    """LIB-14: the admin page filters by user."""
    first = await library.materials.create_sanction.execute(
        admin,
        user_id=student.user_id,
        kind=SanctionKind.WARNING,
        until=None,
        reason="a",
    )
    clock.advance(minutes=1)
    second = await library.materials.create_sanction.execute(
        admin,
        user_id=student.user_id,
        kind=SanctionKind.WARNING,
        until=None,
        reason="b",
    )
    await library.materials.create_sanction.execute(
        admin,
        user_id=other_student.user_id,
        kind=SanctionKind.WARNING,
        until=None,
        reason="c",
    )

    mine = await library.materials.list_sanctions.execute(
        admin, user_id=student.user_id
    )

    assert [s.id for s in mine] == [second.id, first.id]
    assert len(await library.materials.list_sanctions.execute(admin, user_id=None)) == 3
    assert isinstance(mine[0].id, UUID)

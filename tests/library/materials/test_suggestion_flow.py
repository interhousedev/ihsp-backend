"""`/upload/` for students: a suggestion, not a book; librarians decide it."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.enums import SuggestionStatus
from app.modules.library.domain.errors import InvalidTransitionError
from app.modules.library.infrastructure.orm import Item as ItemRow
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import SYSTEM_USER_ID, Actor
from app.shared.base_error import ForbiddenError
from app.shared.contracts.files import FilePurpose
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType
from tests.fakes.clock import FixedClock
from tests.fakes.library.material_files import MaterialFilesApi
from tests.library.catalogue.helpers import make_book_data

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Api = Callable[[Actor | None], Awaitable[AsyncClient]]

FORM = {
    "title": "Optics",
    "authors": ["I. Newton"],
    "language": "en",
    "type": "textbook",
}


async def _suggest(
    library: LibraryServices, student: Actor, files_api: MaterialFilesApi
) -> tuple[UUID, UUID]:
    file_id = files_api.upload(
        student.user_id, name="optics.pdf", purpose=FilePurpose.LIBRARY_MATERIAL
    )
    created = await library.materials.create_suggestion.execute(
        student,
        title="Optics",
        url=None,
        file_id=file_id,
        note=None,
        details=FORM,
    )
    return created.id, file_id


async def _item_count(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with sessionmaker() as session:
        return int(await session.scalar(select(func.count()).select_from(ItemRow)) or 0)


async def test_a_student_upload_is_a_suggestion_not_a_book(
    library: LibraryServices,
    student: Actor,
    files_api: MaterialFilesApi,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """The form and file wait as a pending suggestion; no item is created."""
    before = await _item_count(sessionmaker_in_tx)

    suggestion_id, file_id = await _suggest(library, student, files_api)

    assert await _item_count(sessionmaker_in_tx) == before
    (mine,) = await library.materials.list_my_suggestions.execute(student)
    assert (mine.id, mine.status, mine.file_id) == (
        suggestion_id,
        SuggestionStatus.NEW,
        file_id,
    )


async def test_approve_links_the_book_hands_over_the_file_and_notifies(
    library: LibraryServices,
    student: Actor,
    librarian: Actor,
    files_api: MaterialFilesApi,
    uow_factory: UowFactory,
    outbox: list[NotificationDraft],
) -> None:
    """The librarian saves the edited form as a book, then approves."""
    suggestion_id, file_id = await _suggest(library, student, files_api)
    created = await library.catalogue.create_book.execute(
        librarian, make_book_data(subjects=[], title="Optics (edited)")
    )
    assert created.card.id is not None
    outbox.clear()

    await library.materials.approve_suggestion.execute(
        librarian, suggestion_id, item_id=created.card.id
    )

    async with uow_factory() as uow:
        item = await uow.items.get(created.card.id)
        stored = await uow.moderation.get_suggestion(suggestion_id)
    assert item is not None and [f.file_id for f in item.files] == [file_id]
    assert stored is not None
    assert (stored.status, stored.item_id) == (
        SuggestionStatus.ACCEPTED,
        created.card.id,
    )
    assert (file_id, SYSTEM_USER_ID) in files_api.transferred
    (notice,) = outbox
    assert notice.user_id == student.user_id
    assert notice.type is NotificationType.LIBRARY_SUGGESTION_APPROVED
    assert notice.payload["item_id"] == str(created.card.id)
    with pytest.raises(InvalidTransitionError):
        await library.materials.approve_suggestion.execute(
            librarian, suggestion_id, item_id=created.card.id
        )


async def test_decline_notifies_with_the_reason_and_files_go_after_retention(
    library: LibraryServices,
    student: Actor,
    librarian: Actor,
    files_api: MaterialFilesApi,
    uow_factory: UowFactory,
    outbox: list[NotificationDraft],
    clock: FixedClock,
) -> None:
    """A decline says why; 30 days later the purge job deletes the upload."""
    suggestion_id, file_id = await _suggest(library, student, files_api)
    outbox.clear()

    await library.materials.decide_suggestion.execute(
        librarian, suggestion_id, accept=False, reason="We already have it."
    )

    (notice,) = outbox
    assert notice.type is NotificationType.LIBRARY_SUGGESTION_DECLINED
    assert notice.payload["reason"] == "We already have it."
    (mine,) = await library.materials.list_my_suggestions.execute(student)
    assert (mine.status, mine.reason) == (
        SuggestionStatus.DECLINED,
        "We already have it.",
    )

    await library.materials.purge_files.execute()
    assert file_id not in files_api.deleted
    clock.advance(days=31)
    await library.materials.purge_files.execute()
    assert file_id in files_api.deleted
    async with uow_factory() as uow:
        stored = await uow.moderation.get_suggestion(suggestion_id)
    assert stored is not None and stored.file_id is None


async def test_students_cannot_approve(
    library: LibraryServices, student: Actor, files_api: MaterialFilesApi
) -> None:
    """Approving is for librarians."""
    suggestion_id, _ = await _suggest(library, student, files_api)
    with pytest.raises(ForbiddenError):
        await library.materials.approve_suggestion.execute(
            student, suggestion_id, item_id=new_id()
        )


async def test_http_my_suggestions_and_access_control(
    api: Api,
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    librarian: Actor,
    files_api: MaterialFilesApi,
) -> None:
    """Each person lists only their own; the manage routes refuse students."""
    suggestion_id, file_id = await _suggest(library, student, files_api)

    mine = await (await api(student)).get("/v1/me/library/suggestions")
    theirs = await (await api(other_student)).get("/v1/me/library/suggestions")
    approve = await (await api(student)).post(
        f"/v1/manage/library/suggestions/{suggestion_id}/approve",
        json={"item_id": str(new_id())},
    )
    detail = await (await api(librarian)).get(
        f"/v1/manage/library/suggestions/{suggestion_id}"
    )
    decline = await (await api(librarian)).post(
        f"/v1/manage/library/suggestions/{suggestion_id}/decline",
        json={"reason": "Out of scope."},
    )

    assert mine.status_code == 200
    assert [row["id"] for row in mine.json()["items"]] == [str(suggestion_id)]
    assert theirs.json() == {"items": []}
    assert approve.status_code == 403
    assert detail.json()["file"]["id"] == str(file_id)
    assert decline.status_code == 204


async def test_accept_hands_the_file_and_the_cover_to_the_library(
    library: LibraryServices,
    student: Actor,
    librarian: Actor,
    files_api: MaterialFilesApi,
    uow_factory: UowFactory,
    outbox: list[NotificationDraft],
) -> None:
    """Accepting marks the suggestion and moves both files out of the quota."""
    file_id = files_api.upload(
        student.user_id, name="optics.pdf", purpose=FilePurpose.LIBRARY_MATERIAL
    )
    cover_id = files_api.upload(
        student.user_id,
        name="cover.png",
        content_type="image/png",
        purpose=FilePurpose.LIBRARY_MATERIAL,
    )
    created = await library.materials.create_suggestion.execute(
        student,
        title="Optics",
        url=None,
        file_id=file_id,
        note=None,
        details={**FORM, "cover_file_id": str(cover_id)},
    )
    outbox.clear()

    await library.materials.decide_suggestion.execute(
        librarian, created.id, accept=True
    )

    async with uow_factory() as uow:
        stored = await uow.moderation.get_suggestion(created.id)
    assert stored is not None
    assert (stored.status, stored.handled_by) == (
        SuggestionStatus.ACCEPTED,
        librarian.user_id,
    )
    assert stored.decided_at is not None
    assert (file_id, SYSTEM_USER_ID) in files_api.transferred
    assert (cover_id, SYSTEM_USER_ID) in files_api.transferred
    assert outbox == []
    with pytest.raises(InvalidTransitionError):
        await library.materials.decide_suggestion.execute(
            librarian, created.id, accept=False
        )

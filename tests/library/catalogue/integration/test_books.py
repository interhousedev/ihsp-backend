"""LIB-3: creating, editing, publishing and taking down hosted books."""

import dataclasses
from collections.abc import Callable
from uuid import UUID

from app.modules.library.application.catalogue.list_items import ListItemsQuery
from app.modules.library.domain.catalogue_errors import (
    InvalidFileError,
    InvalidReferenceError,
)
from app.modules.library.domain.entities import SubjectLink
from app.modules.library.domain.enums import (
    EventKind,
    FileFormat,
    ItemStatus,
    Rights,
    TextStatus,
)
from app.modules.library.domain.errors import (
    FileTooLargeError,
    ItemNotFoundError,
    NotEditableError,
    ReasonRequiredError,
    RightsIncompleteError,
)
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft
from tests.fakes.library.files import FakeFilesApi
from tests.fakes.tasks import FakeTaskKicker
from tests.library.catalogue.helpers import make_book_data

import pytest

Upload = Callable[..., UUID]


@pytest.fixture
def upload_book_file(files_api: FakeFilesApi, librarian: Actor) -> Upload:
    """An uploaded file of scope `library` owned by the librarian."""

    def make(
        *,
        owner: Actor | None = None,
        size: int = 100,
        content_type: str = "application/pdf",
    ) -> UUID:
        return files_api.add_file(
            owner_id=(owner or librarian).user_id,
            data=b"x" * size,
            content_type=content_type,
            scope=FileScope.LIBRARY,
            purpose=FilePurpose.LIBRARY_BOOK,
        )

    return make


async def _events(library: LibraryServices, book_id: UUID) -> list[EventKind]:
    async with library.core.uow_factory() as uow:
        return [event.kind for event in await uow.events.history(book_id)]


async def _publishable(
    library: LibraryServices,
    librarian: Actor,
    subject: SubjectLink,
    upload_book_file: Upload,
    **changes: object,
) -> UUID:
    created = await library.catalogue.create_book.execute(
        librarian, make_book_data(subjects=[subject], **changes)
    )
    assert created.card.id is not None
    await library.catalogue.attach_book_file.execute(
        librarian,
        created.card.id,
        file_id=upload_book_file(),
        file_format=FileFormat.PDF,
        is_primary=True,
    )
    async with library.core.uow_factory() as uow:
        item = await uow.items.get(created.card.id)
        assert item is not None and item.primary_file is not None
        item.primary_file.text_status = TextStatus.READY
        await uow.items.save_file(item.primary_file)
        await uow.commit()
    return created.card.id


# - - - Create and edit - - -


async def test_a_librarian_creates_a_draft_with_its_tags_and_history(
    library: LibraryServices, librarian: Actor, physics: SubjectLink
) -> None:
    """LIB-3: the draft is stored with subjects, owner and a `created` event."""
    detail = await library.catalogue.create_book.execute(
        librarian, make_book_data(subjects=[physics])
    )

    assert detail.status is ItemStatus.DRAFT
    assert detail.card.kind.value == "book"
    assert [s.name for s in detail.card.subjects] == ["Physics"]
    assert detail.can.edit
    assert detail.card.id is not None
    assert await _events(library, detail.card.id) == [EventKind.CREATED]


@pytest.mark.parametrize("who", ["student", "teacher"])
async def test_only_librarians_manage_books(
    library: LibraryServices,
    physics: SubjectLink,
    who: str,
    student: Actor,
    teacher: Actor,
) -> None:
    """LIB-3: students and teachers can only suggest books."""
    actor = student if who == "student" else teacher

    with pytest.raises(ForbiddenError):
        await library.catalogue.create_book.execute(
            actor, make_book_data(subjects=[physics])
        )


async def test_administration_may_create_books_too(
    library: LibraryServices, admin: Actor, physics: SubjectLink
) -> None:
    """LIB-3: Administration has all librarian powers."""
    detail = await library.catalogue.create_book.execute(
        admin, make_book_data(subjects=[physics])
    )

    assert detail.status is ItemStatus.DRAFT


async def test_unknown_subject_or_topic_is_refused(
    library: LibraryServices, librarian: Actor
) -> None:
    """LIB-3: tags must exist."""
    with pytest.raises(InvalidReferenceError) as caught:
        await library.catalogue.create_book.execute(
            librarian, make_book_data(subjects=[SubjectLink(new_id())])
        )

    assert caught.value.params["field"] == "subjects"


async def test_cover_must_be_a_file_the_librarian_may_use(
    library: LibraryServices,
    librarian: Actor,
    other_student: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
) -> None:
    """LIB-3: someone else's file cannot become the cover."""
    foreign = upload_book_file(owner=other_student)

    with pytest.raises(InvalidReferenceError):
        await library.catalogue.create_book.execute(
            librarian, make_book_data(subjects=[physics], cover_file_id=foreign)
        )
    with pytest.raises(InvalidReferenceError):
        await library.catalogue.create_book.execute(
            librarian, make_book_data(subjects=[physics], cover_file_id=new_id())
        )


async def test_editing_changes_only_the_sent_fields_and_the_search(
    library: LibraryServices,
    librarian: Actor,
    student: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
) -> None:
    """LIB-3, LIB-7: a PATCH keeps the rest and rebuilds the search text."""
    book_id = await _publishable(library, librarian, physics, upload_book_file)
    await library.catalogue.publish_book.execute(librarian, book_id)

    edited = await library.catalogue.update_book.execute(
        librarian, book_id, {"title": "Kvant fizikasi", "publisher": "Sharq"}
    )

    assert edited.card.title == "Kvant fizikasi"
    assert edited.publisher == "Sharq"
    assert edited.card.author_label == "A. Author"
    found = await library.catalogue.list_items.execute(
        student, ListItemsQuery(q="kvant")
    )
    assert [c.title for c in found.items] == ["Kvant fizikasi"]
    assert EventKind.EDITED in await _events(library, book_id)


async def test_editing_the_rights_of_a_published_book_is_always_allowed(
    library: LibraryServices,
    librarian: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
) -> None:
    """LIB-3: a published book keeps a complete basis."""
    book_id = await _publishable(library, librarian, physics, upload_book_file)
    await library.catalogue.publish_book.execute(librarian, book_id)

    updated = await library.catalogue.update_book.execute(
        librarian, book_id, {"rights_basis": {}}
    )

    assert updated.card.id == book_id


async def test_rights_changes_are_logged(
    library: LibraryServices, librarian: Actor, physics: SubjectLink
) -> None:
    """LIB-3: a change of the rights class leaves a `rights_changed` event."""
    created = await library.catalogue.create_book.execute(
        librarian, make_book_data(subjects=[physics])
    )
    assert created.card.id is not None

    await library.catalogue.update_book.execute(
        librarian,
        created.card.id,
        {"rights": Rights.OPEN_LICENSE, "licence": "CC BY"},
    )

    assert EventKind.RIGHTS_CHANGED in await _events(library, created.card.id)


async def test_a_material_is_not_a_book(
    library: LibraryServices, librarian: Actor
) -> None:
    """LIB-3: the book endpoints never touch materials."""
    from tests.factories.library import make_material

    material = make_material()
    async with library.core.uow_factory() as uow:
        await uow.items.add(material)
        await uow.commit()

    with pytest.raises(ItemNotFoundError):
        await library.catalogue.get_book_draft.execute(librarian, material.id)


# - - - Files - - -


async def test_first_file_becomes_primary_and_the_scan_is_queued(
    library: LibraryServices,
    librarian: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
    kicker: FakeTaskKicker,
) -> None:
    """LIB-3: the file is attached as pending and `process_item_file` is kicked."""
    created = await library.catalogue.create_book.execute(
        librarian, make_book_data(subjects=[physics])
    )
    assert created.card.id is not None
    file_id = upload_book_file()

    attached = await library.catalogue.attach_book_file.execute(
        librarian,
        created.card.id,
        file_id=file_id,
        file_format=FileFormat.PDF,
        is_primary=False,
    )

    assert attached.is_primary
    assert attached.text_status is TextStatus.PENDING
    assert kicker.calls == [
        (
            "library.process_item_file",
            {"item_id": str(created.card.id), "file_id": str(file_id)},
        )
    ]


async def test_a_new_primary_file_replaces_the_old_primary(
    library: LibraryServices,
    librarian: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
) -> None:
    """LIB-3: one primary file per book."""
    created = await library.catalogue.create_book.execute(
        librarian, make_book_data(subjects=[physics])
    )
    assert created.card.id is not None
    first, second = upload_book_file(), upload_book_file()
    for file_id, primary in ((first, True), (second, True)):
        await library.catalogue.attach_book_file.execute(
            librarian,
            created.card.id,
            file_id=file_id,
            file_format=FileFormat.PDF,
            is_primary=primary,
        )

    draft = await library.catalogue.get_book_draft.execute(librarian, created.card.id)

    assert {f.id: f.is_primary for f in draft.item.files} == {
        first: False,
        second: True,
    }


async def test_attaching_the_same_file_twice_changes_nothing(
    library: LibraryServices,
    librarian: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
    kicker: FakeTaskKicker,
) -> None:
    """LIB-3: idempotent."""
    created = await library.catalogue.create_book.execute(
        librarian, make_book_data(subjects=[physics])
    )
    assert created.card.id is not None
    file_id = upload_book_file()
    for _ in range(2):
        await library.catalogue.attach_book_file.execute(
            librarian,
            created.card.id,
            file_id=file_id,
            file_format=FileFormat.PDF,
            is_primary=True,
        )

    assert len(kicker.calls) == 1


@pytest.mark.parametrize(
    "case", ["foreign", "unknown", "wrong_scope", "bad_format", "wrong_type"]
)
async def test_unusable_uploads_are_refused(
    library: LibraryServices,
    librarian: Actor,
    other_student: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
    files_api: FakeFilesApi,
    case: str,
) -> None:
    """LIB-3: the file must be the librarian's, of scope library, of a book format."""
    created = await library.catalogue.create_book.execute(
        librarian, make_book_data(subjects=[physics])
    )
    assert created.card.id is not None
    file_format = FileFormat.PDF
    file_id = upload_book_file()
    if case == "foreign":
        file_id = upload_book_file(owner=other_student)
    elif case == "unknown":
        file_id = new_id()
    elif case == "wrong_scope":
        file_id = files_api.add_file(owner_id=librarian.user_id)
    elif case == "bad_format":
        file_format = FileFormat.DOCX
    else:
        file_format = FileFormat.EPUB

    with pytest.raises(InvalidFileError):
        await library.catalogue.attach_book_file.execute(
            librarian,
            created.card.id,
            file_id=file_id,
            file_format=file_format,
            is_primary=True,
        )


async def test_a_file_over_the_limit_is_too_large(
    library: LibraryServices,
    librarian: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
    files_api: FakeFilesApi,
) -> None:
    """LIB-3: 300 MB per book file."""
    big = upload_book_file()
    stored = files_api.files[big]
    stored.ref = dataclasses.replace(stored.ref, byte_size=400_000_000)
    created = await library.catalogue.create_book.execute(
        librarian, make_book_data(subjects=[physics])
    )
    assert created.card.id is not None

    with pytest.raises(FileTooLargeError):
        await library.catalogue.attach_book_file.execute(
            librarian,
            created.card.id,
            file_id=big,
            file_format=FileFormat.PDF,
            is_primary=True,
        )


# - - - Publish, unpublish, take down - - -


async def test_incomplete_book_is_not_published_and_the_checklist_says_why(
    library: LibraryServices, librarian: Actor, physics: SubjectLink
) -> None:
    """LIB-3: no basis, no text status: 422 with `params.missing[]`."""
    created = await library.catalogue.create_book.execute(
        librarian, make_book_data(subjects=[physics], rights_basis={})
    )
    assert created.card.id is not None

    with pytest.raises(RightsIncompleteError) as caught:
        await library.catalogue.publish_book.execute(librarian, created.card.id)
    draft = await library.catalogue.get_book_draft.execute(librarian, created.card.id)

    assert caught.value.params["missing"] == [
        "text_status",
        "cover",
    ]
    assert [(c.key, c.ok) for c in draft.checklist] == [
        ("text_status", False),
        ("cover", False),
        ("subjects", True),
    ]
    assert draft.data.title == "Physics 10"


async def test_publishing_makes_the_book_visible_and_is_audited(
    audited_library: LibraryServices,
    audit_log: list[AuditDraft],
    librarian: Actor,
    student: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
) -> None:
    """LIB-3: students find it, the rights check is recorded, audit `book_publish`."""
    library = audited_library
    book_id = await _publishable(library, librarian, physics, upload_book_file)
    before = await library.catalogue.list_items.execute(student, ListItemsQuery())

    detail = await library.catalogue.publish_book.execute(librarian, book_id)
    after = await library.catalogue.list_items.execute(student, ListItemsQuery())

    assert before.items == [] and [c.title for c in after.items] == ["Physics 10"]
    assert detail.status is ItemStatus.PUBLISHED
    async with library.core.uow_factory() as uow:
        stored = await uow.items.get(book_id)
    assert stored is not None and stored.book is not None
    assert stored.book.rights_checked_by == librarian.user_id
    assert stored.book.rights_checked_at is not None
    assert [d.type for d in audit_log] == ["library.book_publish"]
    assert audit_log[0].actor_id == librarian.user_id
    assert EventKind.APPROVED in await _events(library, book_id)


async def test_publishing_twice_is_not_editable(
    library: LibraryServices,
    librarian: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
) -> None:
    """LIB-3: `409 library/not-editable` for a book that is already published."""
    book_id = await _publishable(library, librarian, physics, upload_book_file)
    await library.catalogue.publish_book.execute(librarian, book_id)

    with pytest.raises(NotEditableError):
        await library.catalogue.publish_book.execute(librarian, book_id)


async def test_unpublish_hides_the_book_but_keeps_file_and_shelves(
    audited_library: LibraryServices,
    audit_log: list[AuditDraft],
    librarian: Actor,
    student: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
) -> None:
    """LIB-3: unpublished means 404 for students, the librarian still sees it."""
    library = audited_library
    book_id = await _publishable(library, librarian, physics, upload_book_file)
    await library.catalogue.publish_book.execute(librarian, book_id)

    detail = await library.catalogue.unpublish_book.execute(
        librarian, book_id, reason="typo on page 3"
    )

    assert detail.status is ItemStatus.UNPUBLISHED
    assert detail.status_note == "typo on page 3" and len(detail.files) == 1
    with pytest.raises(ItemNotFoundError):
        await library.catalogue.get_item.execute(student, str(book_id))
    assert (await library.catalogue.get_item.execute(librarian, str(book_id))).files
    assert audit_log[-1].type == "library.unpublish"


async def test_takedown_needs_a_reason_and_keeps_it(
    audited_library: LibraryServices,
    audit_log: list[AuditDraft],
    librarian: Actor,
    student: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
) -> None:
    """LIB-3: takedown without reason fails; with one it is kept and audited."""
    library = audited_library
    book_id = await _publishable(library, librarian, physics, upload_book_file)
    await library.catalogue.publish_book.execute(librarian, book_id)

    with pytest.raises(ReasonRequiredError):
        await library.catalogue.takedown_book.execute(librarian, book_id, reason="  ")
    detail = await library.catalogue.takedown_book.execute(
        librarian, book_id, reason="copyright request of the publisher"
    )

    assert detail.status is ItemStatus.UNPUBLISHED
    assert detail.status_reason == "takedown"
    assert detail.status_note == "copyright request of the publisher"
    assert audit_log[-1].type == "library.takedown"
    assert audit_log[-1].metadata is not None
    assert audit_log[-1].metadata["reason"] == "copyright request of the publisher"
    with pytest.raises(ItemNotFoundError):
        await library.catalogue.get_item.execute(student, str(book_id))


async def test_an_unpublished_book_can_be_published_again(
    library: LibraryServices,
    librarian: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
) -> None:
    """LIB-3: after a fix the book goes back to the shelves."""
    book_id = await _publishable(library, librarian, physics, upload_book_file)
    await library.catalogue.publish_book.execute(librarian, book_id)
    await library.catalogue.unpublish_book.execute(librarian, book_id)

    detail = await library.catalogue.publish_book.execute(librarian, book_id)

    assert detail.status is ItemStatus.PUBLISHED and detail.status_reason is None


# - - - The book table - - -


async def test_book_table_lists_every_status_with_filters(
    library: LibraryServices,
    librarian: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
) -> None:
    """LIB-3: drafts and published books, filtered by status and text."""
    live = await _publishable(library, librarian, physics, upload_book_file)
    await library.catalogue.publish_book.execute(librarian, live)
    draft = await library.catalogue.create_book.execute(
        librarian, make_book_data(subjects=[physics], title="Chemistry draft")
    )

    everything = await library.catalogue.list_books.execute(librarian)
    drafts = await library.catalogue.list_books.execute(
        librarian, status=ItemStatus.DRAFT
    )
    searched = await library.catalogue.list_books.execute(librarian, q="physics")

    assert {r.card.title for r in everything.items} == {"Physics 10", "Chemistry draft"}
    assert [r.card.title for r in drafts.items] == ["Chemistry draft"]
    assert [r.card.title for r in searched.items] == ["Physics 10"]
    assert drafts.items[0].status is ItemStatus.DRAFT and draft.card.id is not None
    with pytest.raises(ForbiddenError):
        await library.catalogue.list_books.execute(
            Actor(user_id=new_id(), roles=frozenset())
        )


async def test_published_book_item_survives_a_round_trip_through_the_draft(
    library: LibraryServices,
    librarian: Actor,
    physics: SubjectLink,
    upload_book_file: Upload,
) -> None:
    """LIB-3: the editor gets back what was saved, tags included."""
    book_id = await _publishable(library, librarian, physics, upload_book_file)

    draft = await library.catalogue.get_book_draft.execute(librarian, book_id)

    assert draft.data.subjects == [physics]
    assert draft.data.rights_basis == {"reference": "Order 12/2024"}
    assert all(entry.ok for entry in draft.checklist)

"""LIB-1, LIB-3, LIB-12: the detail of each kind of item, as the caller may see it."""

from collections.abc import Awaitable, Callable

from app.modules.library.domain.entities import Item, SubjectLink
from app.modules.library.domain.enums import ShelfState, Visibility
from app.modules.library.infrastructure.orm import ShelfEntry
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.library import make_book, make_external, make_material
from tests.fakes.library.academic import FakeAcademicDirectory

StoreItem = Callable[[Item], Awaitable[Item]]


async def test_book_detail_has_rights_box_subjects_and_buttons(
    library: LibraryServices,
    store_item: StoreItem,
    academic: FakeAcademicDirectory,
    student: Actor,
) -> None:
    """LIB-3: a book shows its rights statement; a student may read, not download."""
    physics = academic.add_subject(new_id(), "Physics")
    book = await store_item(make_book(title="Fizika 10", visibility=Visibility.LYCEUM))
    async with library.core.uow_factory() as uow:
        await uow.items.set_subject_links(book.id, [SubjectLink(physics)])
        await uow.commit()

    async with library.core.uow_factory() as uow:
        loaded = await uow.items.get(book.id)
        assert loaded is not None
        detail = await library.core.detail.build(
            uow, loaded, viewer=student, locale="en"
        )

    assert detail.card.tag_label == "Library book"
    assert [s.name for s in detail.card.subjects] == ["Physics"]
    assert detail.rights_box is not None and "textbook" in detail.rights_box.text
    assert detail.can.read and not detail.can.download
    assert detail.can.add_to_notebook and detail.can.report and not detail.can.edit


async def test_external_detail_has_no_content_buttons(
    library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-12: a UniLibrary record offers only the link-out and report."""
    record = await store_item(make_external())

    async with library.core.uow_factory() as uow:
        loaded = await uow.items.get(record.id)
        assert loaded is not None
        detail = await library.core.detail.build(
            uow, loaded, viewer=student, locale="uz"
        )

    assert detail.card.external is not None
    assert detail.card.external.field_name == "Fizika"
    assert not (detail.can.read or detail.can.download or detail.can.add_to_notebook)
    assert detail.files == ()


async def test_material_card_shows_attribution_shelf_and_progress(
    library: LibraryServices,
    store_item: StoreItem,
    student: Actor,
    other_student: Actor,
) -> None:
    """LIB-13: "Aziza K., 2025"; the viewer's shelf state comes with the card."""
    material = await store_item(make_material(uploader_id=other_student.user_id))
    async with library.core.uow_factory() as uow:
        uow.shelf.session.add(  # type: ignore[attr-defined]
            ShelfEntry(
                user_id=student.user_id,
                item_id=material.id,
                state=ShelfState.READING.value,
            )
        )
        await uow.commit()

    async with library.core.uow_factory() as uow:
        (card,) = await library.core.cards.build(
            uow, [material], viewer=student, locale="en"
        )

    assert card.material is not None and card.material.uploader_name == "Aziza K."
    assert card.shelf_state is ShelfState.READING
    assert card.tag_source == "material"

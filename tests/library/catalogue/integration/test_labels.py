"""Authors and tags: get-or-create, fuzzy search across scripts, tags on books."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.application.catalogue.list_items import ListItemsQuery
from app.modules.library.domain.entities import Item, SubjectLink
from app.modules.library.domain.enums import ItemStatus, SubjectRole
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from tests.factories.library import make_book
from tests.library.catalogue.helpers import make_book_data, put

import pytest
import pytest_asyncio

StoreItem = Callable[[Item], Awaitable[Item]]


async def authors(factory: UowFactory, text: str) -> list[str]:
    async with factory() as uow:
        return [a.name for a in await uow.labels.search_authors(text, limit=10)]


@pytest_asyncio.fixture
async def classics(
    library: LibraryServices, librarian: Actor, physics: SubjectLink
) -> None:
    """Two books by classics, one author spelled in Cyrillic."""
    create = library.catalogue.create_book.execute
    await create(
        librarian,
        make_book_data(
            subjects=[physics],
            title="Xamsa",
            authors=["Alisher Navoiy"],
            tags=["Classic", "Poetry"],
        ),
    )
    await create(
        librarian,
        make_book_data(
            subjects=[physics],
            title="O'tkan kunlar",
            authors=["Abdulla Qodiriy", "Алишер Навои"],
            tags=["classic", "Novel"],
        ),
    )


async def test_one_author_row_per_person_whatever_the_script(
    library: LibraryServices, classics: None
) -> None:
    """`Алишер Навои` on the second book is the author of the first one."""
    assert await authors(library.core.uow_factory, "") == []  # nothing typed
    assert await authors(library.core.uow_factory, "navoiy") == ["Alisher Navoiy"]
    assert await authors(library.core.uow_factory, "Навои") == ["Alisher Navoiy"]


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("Navoiy", "Alisher Navoiy"),
        ("Навои", "Alisher Navoiy"),
        ("алишер нав", "Alisher Navoiy"),
        ("Абдулла Кадыри", "Abdulla Qodiriy"),
        ("kodiriy", "Abdulla Qodiriy"),
        ("Qodirij", "Abdulla Qodiriy"),
    ],
)
async def test_authors_are_found_while_typing_in_either_script(
    library: LibraryServices, classics: None, typed: str, expected: str
) -> None:
    """Prefixes, other script and typos find the stored name, best match first."""
    assert (await authors(library.core.uow_factory, typed))[0] == expected


async def test_search_endpoint_use_case_returns_names(
    library: LibraryServices, classics: None, student: Actor
) -> None:
    """Any signed-in user may ask; the answer is a list of names."""
    names = await library.catalogue.search_authors.execute(student, "Qodir")
    assert names == ["Abdulla Qodiriy"]


async def test_tags_are_created_once_and_reused(
    library: LibraryServices, classics: None, student: Actor
) -> None:
    """`Classic` and `classic` are one tag; counts are of published items only."""
    all_tags = await library.catalogue.search_tags.execute(student, "")
    assert {t.name: t.item_count for t in all_tags} == {
        "Classic": 0,
        "Poetry": 0,
        "Novel": 0,
    }
    found = await library.catalogue.search_tags.execute(student, "clas")
    assert [t.name for t in found] == ["Classic"]
    cyrillic = await library.catalogue.search_tags.execute(student, "Классик")
    assert [t.name for t in cyrillic][:1] == ["Classic"]


async def test_editing_replaces_authors_and_tags(
    library: LibraryServices, librarian: Actor, physics: SubjectLink
) -> None:
    """PATCH with new names relinks; the old author row stays for suggestions."""
    created = await library.catalogue.create_book.execute(
        librarian,
        make_book_data(subjects=[physics], authors=["A. Author"], tags=["one", "two"]),
    )
    assert created.tags == ("one", "two")
    book_id = created.card.id
    assert book_id is not None

    changed = await library.catalogue.update_book.execute(
        librarian, book_id, {"authors": ["B. Writer"], "tags": ["two", "three"]}
    )
    draft = await library.catalogue.get_book_draft.execute(librarian, book_id)

    assert changed.tags == ("three", "two")
    assert draft.data.tags == ["three", "two"]
    assert draft.data.authors == ["B. Writer"]
    assert await authors(library.core.uow_factory, "writer") == ["B. Writer"]
    assert await authors(library.core.uow_factory, "author") == ["A. Author"]


async def test_catalogue_filters_by_tag(
    library: LibraryServices,
    student: Actor,
    store_item: StoreItem,
) -> None:
    """`?tag=` narrows to visible items with the tag, in any spelling or case."""
    mechanics = make_book(title="Mechanics")
    optics = make_book(title="Optics", status=ItemStatus.HELD)
    for book, tag in ((mechanics, "Olympiad"), (optics, "Lab")):
        await store_item(book)
        async with library.core.uow_factory() as uow:
            await uow.labels.set_item_tags(book.id, [tag, "Physics"])
            await uow.commit()

    tagged = await library.catalogue.list_items.execute(
        student, ListItemsQuery(tag="olympiad")
    )
    held = await library.catalogue.list_items.execute(
        student, ListItemsQuery(tag="Lab")
    )
    shared = await library.catalogue.list_items.execute(
        student, ListItemsQuery(tag="physics")
    )
    popular = await library.catalogue.search_tags.execute(student, "")

    assert [c.title for c in tagged.items] == ["Mechanics"]
    assert held.items == []  # a held book is not shown to students
    assert [c.title for c in shared.items] == ["Mechanics"]
    assert {t.name: t.item_count for t in popular}["Physics"] == 1
    assert popular[-1].name == "Lab"  # the least used (held book only) is last


async def test_subject_filter_includes_sub_subjects(
    library: LibraryServices, librarian: Actor, store_item: StoreItem
) -> None:
    """A book under `Physics` shows when browsing `Natural sciences`, not `Arts`."""
    create = library.taxonomy.create_subject.execute
    science = (await create(librarian, name={"en": "Natural sciences"})).id
    physics = (await create(librarian, name={"en": "Physics"}, parent_id=science)).id
    arts = (await create(librarian, name={"en": "Arts"})).id
    await put(
        library.core.uow_factory,
        store_item,
        make_book(title="Kvant"),
        subjects=[SubjectLink(physics, SubjectRole.TEXTBOOK)],
    )

    def browse(subject: UUID) -> ListItemsQuery:
        return ListItemsQuery(subject_id=subject)

    in_science = await library.catalogue.list_items.execute(librarian, browse(science))
    in_physics = await library.catalogue.list_items.execute(librarian, browse(physics))
    in_arts = await library.catalogue.list_items.execute(librarian, browse(arts))
    subjects = await library.catalogue.list_subjects.execute(
        librarian, include_empty=True
    )

    assert [c.title for c in in_science.items] == ["Kvant"]
    assert [c.title for c in in_physics.items] == ["Kvant"]
    assert in_arts.items == []
    assert {s.id: s.parent_id for s in subjects}[physics] == science
    assert {s.id: s.item_count for s in subjects}[science] == 1

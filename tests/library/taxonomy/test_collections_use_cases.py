"""LIB-4, LIB-2: curated collections, public reading and librarian management."""

from collections.abc import Awaitable, Callable
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemStatus, Rights, Visibility
from app.modules.library.domain.errors import CollectionNotFoundError, ItemNotFoundError
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_collections import COLLECTION_MAX_ITEMS
from app.modules.library.domain.taxonomy_errors import (
    CollectionTooLongError,
    CoverInvalidError,
    NameRequiredError,
)
from app.modules.library.domain.taxonomy_unset import UNSET
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.contracts.files import FilePurpose, FileScope
from app.shared.ids import new_id
from tests.factories.library import make_book
from tests.fakes.library.files import FakeFilesApi
from tests.library.taxonomy.conftest import Recorded

import pytest

StoreItem = Callable[[Item], Awaitable[Item]]
TITLE = {"uz": "Oʻzbek klassikasi", "ru": "Узбекская классика", "en": "Uzbek classics"}


async def public_book(store_item: StoreItem, title: str = "Public book") -> Item:
    return await store_item(
        make_book(
            title=title, visibility=Visibility.PUBLIC, rights=Rights.PUBLIC_DOMAIN
        )
    )


async def lyceum_book(store_item: StoreItem, title: str = "Lyceum book") -> Item:
    return await store_item(make_book(title=title))


# - - - Managing - - -


async def test_librarian_creates_a_collection_with_ordered_items(
    library: LibraryServices,
    librarian: Actor,
    store_item: StoreItem,
    recorded: Recorded,
) -> None:
    """LIB-4, LIB-2: CollectionInput carries the items; the action is audited."""
    first, second = await lyceum_book(store_item), await lyceum_book(store_item)

    view = await library.taxonomy.create_collection.execute(
        librarian,
        title=TITLE,
        description={"en": "Core reading"},
        published=True,
        item_ids=[second.id, first.id, second.id],
    )

    assert view.item_ids == (second.id, first.id)
    assert view.title == {**TITLE}
    assert view.description == {"uz": "", "ru": "", "en": "Core reading"}
    assert view.slug.startswith("uzbek-classics-")
    assert (view.published, view.position, view.cover_url) == (True, 0, None)
    (event,) = recorded.audits
    assert event.type == TaxonomyAuditType.COLLECTION_CREATE
    assert event.metadata is not None and event.metadata["item_count"] == 2


async def test_new_collections_go_last_and_a_blank_description_is_none(
    library: LibraryServices, librarian: Actor
) -> None:
    """LIB-4: positions grow; no description gives null."""
    one = await library.taxonomy.create_collection.execute(librarian, title=TITLE)
    two = await library.taxonomy.create_collection.execute(
        librarian, title=TITLE, description={"en": " "}
    )

    assert (one.position, two.position) == (0, 1)
    assert two.description is None
    assert one.slug != two.slug
    assert one.published is False


async def test_items_must_exist_and_the_list_is_limited(
    library: LibraryServices, librarian: Actor
) -> None:
    """LIB-4: unknown items are a not-found; very long shelves are refused."""
    with pytest.raises(ItemNotFoundError):
        await library.taxonomy.create_collection.execute(
            librarian, title=TITLE, item_ids=[new_id()]
        )
    with pytest.raises(CollectionTooLongError):
        await library.taxonomy.create_collection.execute(
            librarian,
            title=TITLE,
            item_ids=[new_id() for _ in range(COLLECTION_MAX_ITEMS + 1)],
        )
    with pytest.raises(NameRequiredError):
        await library.taxonomy.create_collection.execute(
            librarian, title={"uz": "", "ru": "", "en": ""}
        )


async def test_cover_must_be_a_stored_library_cover(
    library: LibraryServices, librarian: Actor, files_api: FakeFilesApi
) -> None:
    """LIB-4: cover_file_id points at a file uploaded as a library cover."""
    cover = files_api.add_file(
        owner_id=librarian.user_id,
        purpose=FilePurpose.LIBRARY_COVER,
        scope=FileScope.LIBRARY,
    )
    document = files_api.add_file(owner_id=librarian.user_id, purpose=FilePurpose.LINK)

    ok = await library.taxonomy.create_collection.execute(
        librarian, title=TITLE, cover_file_id=cover
    )
    with pytest.raises(CoverInvalidError):
        await library.taxonomy.create_collection.execute(
            librarian, title=TITLE, cover_file_id=document
        )
    with pytest.raises(CoverInvalidError):
        await library.taxonomy.create_collection.execute(
            librarian, title=TITLE, cover_file_id=new_id()
        )

    assert ok.cover_url is not None and str(cover) in ok.cover_url


async def test_update_changes_only_what_was_sent(
    library: LibraryServices,
    librarian: Actor,
    store_item: StoreItem,
    files_api: FakeFilesApi,
    recorded: Recorded,
) -> None:
    """LIB-4: PATCH keeps the slug; null clears description and cover."""
    book, other = await lyceum_book(store_item), await lyceum_book(store_item)
    cover = files_api.add_file(
        owner_id=librarian.user_id,
        purpose=FilePurpose.LIBRARY_COVER,
        scope=FileScope.LIBRARY,
    )
    created = await library.taxonomy.create_collection.execute(
        librarian,
        title=TITLE,
        description={"en": "Text"},
        cover_file_id=cover,
        item_ids=[book.id],
    )

    renamed = await library.taxonomy.update_collection.execute(
        librarian, created.id, title={"uz": "Yangi", "ru": "", "en": ""}, published=True
    )
    cleared = await library.taxonomy.update_collection.execute(
        librarian, created.id, description=None, cover_file_id=None
    )
    replaced = await library.taxonomy.update_collection.execute(
        librarian, created.id, item_ids=[other.id, book.id]
    )
    untouched = await library.taxonomy.update_collection.execute(
        librarian, created.id, title=UNSET
    )

    assert renamed.title["uz"] == "Yangi"
    assert renamed.slug == created.slug
    assert renamed.published and renamed.item_ids == (book.id,)
    assert cleared.description is None and cleared.cover_url is None
    assert replaced.item_ids == (other.id, book.id)
    assert untouched.title["uz"] == "Yangi"
    assert recorded.audits[-1].type == TaxonomyAuditType.COLLECTION_UPDATE


async def test_delete_removes_the_collection(
    library: LibraryServices, librarian: Actor, recorded: Recorded
) -> None:
    """LIB-4: DELETE /manage/library/collections/{id}."""
    created = await library.taxonomy.create_collection.execute(
        librarian, title=TITLE, published=True
    )

    await library.taxonomy.delete_collection.execute(librarian, created.id)

    assert await library.taxonomy.list_manage_collections.execute(librarian) == []
    with pytest.raises(CollectionNotFoundError):
        await library.taxonomy.delete_collection.execute(librarian, created.id)
    with pytest.raises(CollectionNotFoundError):
        await library.taxonomy.update_collection.execute(
            librarian, created.id, published=False
        )
    assert recorded.audits[-1].type == TaxonomyAuditType.COLLECTION_DELETE


async def test_only_librarians_and_admins_manage_collections(
    library: LibraryServices, student: Actor, teacher: Actor, admin: Actor
) -> None:
    """LIB-2: collections are the librarians' shelves."""
    for actor in (student, teacher):
        with pytest.raises(ForbiddenError):
            await library.taxonomy.create_collection.execute(actor, title=TITLE)
        with pytest.raises(ForbiddenError):
            await library.taxonomy.list_manage_collections.execute(actor)

    created = await library.taxonomy.create_collection.execute(admin, title=TITLE)
    listed = await library.taxonomy.list_manage_collections.execute(admin)

    assert [c.id for c in listed] == [created.id]


# - - - Reading - - -


async def test_public_list_has_only_published_collections_with_visible_counts(
    library: LibraryServices,
    librarian: Actor,
    student: Actor,
    store_item: StoreItem,
) -> None:
    """LIB-4: counts include only the items the viewer may see."""
    public = await public_book(store_item)
    lyceum = await lyceum_book(store_item)
    held = await store_item(make_book(title="Held", status=ItemStatus.HELD))
    shelf = await library.taxonomy.create_collection.execute(
        librarian,
        title=TITLE,
        published=True,
        item_ids=[public.id, lyceum.id, held.id],
    )
    await library.taxonomy.create_collection.execute(
        librarian, title={"en": "Draft"}, published=False
    )

    anonymous = await library.taxonomy.list_collections.execute(
        None, accept_language="uz"
    )
    signed_in = await library.taxonomy.list_collections.execute(student)

    assert [c.id for c in anonymous] == [shelf.id] == [c.id for c in signed_in]
    assert anonymous[0].title == "Oʻzbek klassikasi"
    assert signed_in[0].title == "Uzbek classics"
    assert (anonymous[0].item_count, signed_in[0].item_count) == (1, 2)
    assert anonymous[0].description is None


async def test_collection_detail_has_cards_of_visible_items_in_order(
    library: LibraryServices,
    librarian: Actor,
    student: Actor,
    store_item: StoreItem,
) -> None:
    """LIB-4: GET /collections/{id} answers cards; hidden items are left out."""
    public = await public_book(store_item, "Alpha")
    lyceum = await lyceum_book(store_item, "Beta")
    held = await store_item(make_book(title="Gamma", status=ItemStatus.HELD))
    shelf = await library.taxonomy.create_collection.execute(
        librarian,
        title=TITLE,
        published=True,
        item_ids=[lyceum.id, held.id, public.id],
    )

    as_student = await library.taxonomy.get_collection.execute(student, str(shelf.id))
    as_visitor = await library.taxonomy.get_collection.execute(None, shelf.slug)

    assert [c.title for c in as_student.items] == ["Beta", "Alpha"]
    assert [c.title for c in as_visitor.items] == ["Alpha"]
    assert as_visitor.collection.item_count == 1
    assert as_student.collection.id == shelf.id


async def test_unpublished_or_missing_collection_is_a_404_even_for_librarians(
    library: LibraryServices, librarian: Actor
) -> None:
    """LIB-4: the manage endpoints are for drafts; the public one says not found."""
    draft = await library.taxonomy.create_collection.execute(
        librarian, title=TITLE, published=False
    )

    for viewer in (None, librarian):
        with pytest.raises(CollectionNotFoundError):
            await library.taxonomy.get_collection.execute(viewer, str(draft.id))
        with pytest.raises(CollectionNotFoundError):
            await library.taxonomy.get_collection.execute(viewer, draft.slug)
    with pytest.raises(CollectionNotFoundError):
        await library.taxonomy.get_collection.execute(None, str(new_id()))


async def test_manage_list_shows_drafts_with_all_item_ids(
    library: LibraryServices, librarian: Actor, store_item: StoreItem
) -> None:
    """LIB-2: the librarian's list has every collection, published or not."""
    book = await lyceum_book(store_item)
    await library.taxonomy.create_collection.execute(
        librarian, title={"en": "B"}, item_ids=[book.id]
    )
    await library.taxonomy.create_collection.execute(
        librarian, title={"en": "A"}, published=True
    )

    listed = await library.taxonomy.list_manage_collections.execute(librarian)

    assert [c.title["en"] for c in listed] == ["B", "A"]
    assert listed[0].item_ids == (book.id,)


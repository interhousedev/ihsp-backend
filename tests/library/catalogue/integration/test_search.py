"""LIB-7, LIB-1: catalogue search over the real database.

Full-text hits with snippet and page, Uzbek Latin and Cyrillic meeting each other,
filters, ranking, pagination and the visibility rules that keep held, hidden and
unpublished items out of every result.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.catalogue_search import (
    ItemFilters,
    ItemSort,
    ItemSource,
    Viewer,
    viewer_from_actor,
)
from app.modules.library.domain.entities import Item, SubjectLink, TopicLink
from app.modules.library.domain.enums import (
    ItemLanguage,
    ItemStatus,
    ItemType,
    Rights,
    ShelfState,
    UploaderRole,
    Visibility,
)
from app.modules.library.domain.search_query import parse_query
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.library import NOW, make_book, make_external, make_material
from tests.library.catalogue.helpers import (
    add_collection,
    add_shelf,
    add_topic,
    hit_ids,
    put,
)

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

StoreItem = Callable[[Item], Awaitable[Item]]
ANON = Viewer()


def _filters(text: str | None = None, **fields: object) -> ItemFilters:
    query = parse_query(text) if text else None
    return ItemFilters(query=query, **fields)  # type: ignore[arg-type]


async def _search(
    uow_factory: UowFactory,
    filters: ItemFilters,
    viewer: Viewer,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[UUID]:
    async with uow_factory() as uow:
        return hit_ids(
            await uow.items.search(filters, viewer, limit=limit, offset=offset)
        )


def _member(actor: Actor) -> Viewer:
    return viewer_from_actor(actor, anonymous_cards=False)


# - - - Text matching - - -


async def test_title_words_find_the_book(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: a word of the title finds the item; others do not."""
    physics = await put(uow_factory, store_item, make_book(title="Fizika 10"))
    await put(uow_factory, store_item, make_book(title="Kimyo 10"))

    found = await _search(uow_factory, _filters("fizika"), _member(student))

    assert found == [physics.id]


async def test_last_word_matches_as_a_prefix(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: search as you type finds "adabiyot" from "adab"."""
    book = await put(uow_factory, store_item, make_book(title="Adabiyot 10"))

    assert await _search(uow_factory, _filters("adab"), _member(student)) == [book.id]


async def test_author_and_description_are_searched(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: titles, authors and descriptions all count."""
    by_author = await put(
        uow_factory,
        store_item,
        make_book(title="Kitob A", authors=["Abdulla Qodiriy"]),
    )
    by_text = await put(
        uow_factory,
        store_item,
        make_book(title="Kitob B", description="O'tkan kunlar haqida"),
    )

    assert await _search(uow_factory, _filters("qodiriy"), _member(student)) == [
        by_author.id
    ]
    assert await _search(uow_factory, _filters("kunlar"), _member(student)) == [
        by_text.id
    ]


async def test_cyrillic_query_finds_latin_uzbek_item(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: "ўзбек" finds "Oʻzbek adabiyoti" and "O'zbek adabiyoti"."""
    book = await put(uow_factory, store_item, make_book(title="O'zbek adabiyoti"))

    assert await _search(uow_factory, _filters("ўзбек"), _member(student)) == [book.id]


async def test_latin_query_finds_cyrillic_uzbek_item(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: the Cyrillic title is stored Latin-normalised, so Latin finds it."""
    book = await put(
        uow_factory,
        store_item,
        make_book(title="Ўзбек адабиёти", language=ItemLanguage.UZ_CYRL),
    )

    for typed in ("oʻzbek", "o'zbek", "oʻzbek adab"):
        assert await _search(uow_factory, _filters(typed), _member(student)) == [
            book.id
        ]


async def test_russian_query_finds_russian_item_untransliterated(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: Russian items stay Cyrillic in the index and are found as typed."""
    russian = await put(
        uow_factory,
        store_item,
        make_book(title="Физика 10 класс", language=ItemLanguage.RU),
    )
    await put(uow_factory, store_item, make_book(title="Fizika 10"))

    found = await _search(uow_factory, _filters("физика"), _member(student))

    assert russian.id in found


async def test_title_typo_is_found_by_trigram_similarity(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: a slip of the finger still finds the title (trigram similarity)."""
    book = await put(uow_factory, store_item, make_book(title="Trigonometriya"))

    found = await _search(uow_factory, _filters("trigonometria"), _member(student))

    assert found == [book.id]


async def test_blank_query_means_no_text_filter(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: without a query all visible items are listed."""
    first = await put(uow_factory, store_item, make_book(title="Fizika"))
    second = await put(uow_factory, store_item, make_book(title="Kimyo"))

    found = await _search(uow_factory, _filters(), _member(student))

    assert set(found) == {first.id, second.id}


# - - - Full-text hits - - -


async def test_body_text_hit_has_snippet_and_page(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: a hit in the body of a book carries the snippet and the page."""
    book = await put(
        uow_factory,
        store_item,
        make_book(title="Mexanika"),
        pages=[
            "Birinchi bob. Kirish.",
            "Nyutonning ikkinchi qonuni: kuch massa va tezlanish ko'paytmasiga teng.",
        ],
    )

    async with uow_factory() as uow:
        hits = await uow.items.search(
            _filters("tezlanish"), _member(student), limit=10, offset=0
        )

    assert [hit.item_id for hit in hits] == [book.id]
    assert hits[0].page == 2
    assert hits[0].snippet is not None and "tezlanish" in hits[0].snippet
    assert "⟦" not in hits[0].snippet


async def test_latin_query_finds_cyrillic_body_text(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: the page text of an Uzbek book is indexed Latin-normalised."""
    book = await put(
        uow_factory,
        store_item,
        make_book(title="Kitob", language=ItemLanguage.UZ_CYRL),
        pages=["Ғазал — ўзбек адабиётининг қадимий жанри."],
    )

    async with uow_factory() as uow:
        hits = await uow.items.search(
            _filters("gʻazal"), _member(student), limit=10, offset=0
        )

    assert [hit.item_id for hit in hits] == [book.id]
    assert hits[0].page == 1
    assert hits[0].snippet and "gʻazal" in hits[0].snippet


async def test_title_hit_without_body_match_has_no_snippet(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: snippet and page appear only for full-text hits."""
    await put(
        uow_factory,
        store_item,
        make_book(title="Fizika"),
        pages=["Birinchi sahifa"],
    )

    async with uow_factory() as uow:
        hits = await uow.items.search(
            _filters("fizika"), _member(student), limit=10, offset=0
        )

    assert len(hits) == 1
    assert hits[0].snippet is None and hits[0].page is None


# - - - Filters - - -


async def test_source_filter_separates_books_materials_and_external(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: source=book|material|external."""
    book = await put(uow_factory, store_item, make_book(title="Kitob"))
    material = await put(uow_factory, store_item, make_material(title="Konspekt"))
    record = await put(uow_factory, store_item, make_external(title="Elektronika"))
    viewer = _member(student)

    assert await _search(uow_factory, _filters(source=ItemSource.BOOK), viewer) == [
        book.id
    ]
    assert await _search(uow_factory, _filters(source=ItemSource.MATERIAL), viewer) == [
        material.id
    ]
    assert await _search(uow_factory, _filters(source=ItemSource.EXTERNAL), viewer) == [
        record.id
    ]
    assert set(await _search(uow_factory, _filters(), viewer)) == {
        book.id,
        material.id,
        record.id,
    }


async def test_subject_and_topic_filters(
    uow_factory: UowFactory,
    store_item: StoreItem,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    student: Actor,
) -> None:
    """LIB-7: subject_id and topic_id narrow the list."""
    physics, chemistry = new_id(), new_id()
    topic = await add_topic(sessionmaker_in_tx, physics)
    with_physics = await put(
        uow_factory,
        store_item,
        make_book(title="Fizika"),
        subjects=[SubjectLink(physics)],
        topics=[TopicLink(topic, page_from=10, page_to=20)],
    )
    await put(
        uow_factory,
        store_item,
        make_book(title="Kimyo"),
        subjects=[SubjectLink(chemistry)],
    )
    viewer = _member(student)

    assert await _search(uow_factory, _filters(subject_id=physics), viewer) == [
        with_physics.id
    ]
    assert await _search(uow_factory, _filters(topic_id=topic), viewer) == [
        with_physics.id
    ]
    assert await _search(uow_factory, _filters(topic_id=new_id()), viewer) == []


async def test_year_filter_keeps_untagged_items(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: an item for year 1 is not listed for year 2; untagged means any year."""
    first = await put(
        uow_factory, store_item, make_book(title="Birinchi", years_of_study=[1])
    )
    second = await put(
        uow_factory, store_item, make_book(title="Ikkinchi", years_of_study=[2])
    )
    anyone = await put(uow_factory, store_item, make_book(title="Hammaga"))

    found = await _search(uow_factory, _filters(year_of_study=2), _member(student))

    assert set(found) == {second.id, anyone.id}
    assert first.id not in found


async def test_type_language_and_has_text_filters(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: type, language (uz covers both scripts) and has_text."""
    manual = await put(
        uow_factory, store_item, make_book(title="Qoʻllanma", type=ItemType.MANUAL)
    )
    russian = await put(
        uow_factory,
        store_item,
        make_book(title="Учебник", language=ItemLanguage.RU),
    )
    cyrillic = await put(
        uow_factory,
        store_item,
        make_book(title="Дарслик", language=ItemLanguage.UZ_CYRL, has_text=False),
    )
    viewer = _member(student)

    assert await _search(uow_factory, _filters(type=ItemType.MANUAL), viewer) == [
        manual.id
    ]
    assert await _search(uow_factory, _filters(language="ru"), viewer) == [russian.id]
    assert set(await _search(uow_factory, _filters(language="uz"), viewer)) == {
        manual.id,
        cyrillic.id,
    }
    assert cyrillic.id not in await _search(
        uow_factory, _filters(has_text=True), viewer
    )
    assert await _search(uow_factory, _filters(has_text=False), viewer) == [cyrillic.id]


async def test_uploader_role_filter_lists_materials_of_that_role(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: uploader_role=teacher|student (plain text, not a trust signal)."""
    by_teacher = await put(
        uow_factory,
        store_item,
        make_material(title="Teacher notes", uploader_role=UploaderRole.TEACHER),
    )
    await put(uow_factory, store_item, make_material(title="Student notes"))

    found = await _search(
        uow_factory, _filters(uploader_role=UploaderRole.TEACHER), _member(student)
    )

    assert found == [by_teacher.id]


async def test_shelf_filter_lists_only_my_shelf(
    uow_factory: UowFactory,
    store_item: StoreItem,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    student: Actor,
    other_student: Actor,
) -> None:
    """LIB-7: "on my shelf" uses the caller's shelf, never someone else's."""
    mine = await put(uow_factory, store_item, make_book(title="Mening kitobim"))
    theirs = await put(uow_factory, store_item, make_book(title="Uning kitobi"))
    await add_shelf(sessionmaker_in_tx, student, mine, ShelfState.WANT)
    await add_shelf(sessionmaker_in_tx, other_student, theirs, ShelfState.DONE)

    found = await _search(uow_factory, _filters(shelf="any"), _member(student))
    done = await _search(uow_factory, _filters(shelf=ShelfState.DONE), _member(student))
    anonymous = await _search(uow_factory, _filters(shelf="any"), ANON)

    assert found == [mine.id]
    assert done == []
    assert anonymous == []


async def test_collection_filter(
    uow_factory: UowFactory,
    store_item: StoreItem,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    student: Actor,
) -> None:
    """LIB-7: collection_id lists the items curated into the collection."""
    book = await put(uow_factory, store_item, make_book(title="Klassika"))
    await put(uow_factory, store_item, make_book(title="Boshqa"))
    collection_id = await add_collection(sessionmaker_in_tx, [book])

    found = await _search(
        uow_factory, _filters(collection_id=collection_id), _member(student)
    )

    assert found == [book.id]


# - - - Visibility - - -


@pytest_asyncio.fixture
async def shelfful(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> dict[str, Item]:
    """One item per status/visibility; the student owns `own_draft`."""
    spec: dict[str, Item] = {
        "public": make_book(
            title="Public book",
            visibility=Visibility.PUBLIC,
            rights=Rights.PUBLIC_DOMAIN,
        ),
        "lyceum": make_book(title="Lyceum book"),
        "hidden": make_book(title="Hidden book", visibility=Visibility.HIDDEN),
        "held": make_material(title="Held material", status=ItemStatus.HELD),
        "unpublished": make_book(title="Gone book", status=ItemStatus.UNPUBLISHED),
        "pending": make_material(
            title="Pending material", status=ItemStatus.PENDING_REVIEW
        ),
        "draft": make_book(title="Draft book", status=ItemStatus.DRAFT),
        "own_draft": make_material(
            title="My draft",
            status=ItemStatus.DRAFT,
            uploader_id=student.user_id,
        ),
        "external": make_external(title="UniLibrary record"),
    }
    for item in spec.values():
        await put(uow_factory, store_item, item)
    return spec


async def test_anonymous_sees_only_public_published_items(
    uow_factory: UowFactory, shelfful: dict[str, Item]
) -> None:
    """LIB-1: visitors get public books only, never lyceum, held or UniLibrary."""
    found = await _search(uow_factory, _filters(), ANON)

    assert found == [shelfful["public"].id]


async def test_anonymous_sees_external_cards_only_when_the_setting_allows(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-1: UniLibrary cards for visitors need Administration's switch (Q10)."""
    record = make_external(title="Public card", visibility=Visibility.PUBLIC)
    await put(uow_factory, store_item, record)
    gone = make_external(
        title="Removed card", external_id="9", visibility=Visibility.PUBLIC
    )
    assert gone.external is not None
    gone.external.gone_at = NOW
    await put(uow_factory, store_item, gone)

    off = await _search(uow_factory, _filters(), Viewer())
    on = await _search(uow_factory, _filters(), Viewer(anonymous_cards=True))

    assert off == []
    assert on == [record.id]


async def test_student_never_sees_held_hidden_unpublished_or_pending(
    uow_factory: UowFactory, shelfful: dict[str, Item], student: Actor
) -> None:
    """LIB-1: held, hidden, unpublished and unreviewed items stay out of the lists."""
    found = set(await _search(uow_factory, _filters(), _member(student)))

    assert found == {
        shelfful["public"].id,
        shelfful["lyceum"].id,
        shelfful["external"].id,
        shelfful["own_draft"].id,
    }


async def test_other_student_does_not_see_the_draft_of_the_first(
    uow_factory: UowFactory, shelfful: dict[str, Item], other_student: Actor
) -> None:
    """LIB-1: only the owner sees a draft."""
    found = await _search(uow_factory, _filters(), _member(other_student))

    assert shelfful["own_draft"].id not in found


async def test_librarian_sees_reviewable_items_but_not_other_drafts(
    uow_factory: UowFactory, shelfful: dict[str, Item], other_librarian: Actor
) -> None:
    """LIB-1: staff see held, hidden, unpublished and pending items for review."""
    found = set(await _search(uow_factory, _filters(), _member(other_librarian)))

    assert {
        shelfful[name].id
        for name in ("public", "lyceum", "hidden", "held", "unpublished", "pending")
    } <= found
    assert shelfful["draft"].id not in found
    assert shelfful["own_draft"].id not in found


async def test_text_hits_respect_visibility_too(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-1: a held item's body text never shows up in a student's search."""
    await put(
        uow_factory,
        store_item,
        make_material(title="Imtihon", status=ItemStatus.HELD),
        pages=["Maxfiy savol: tezlanish nima?"],
    )

    assert await _search(uow_factory, _filters("tezlanish"), _member(student)) == []


# - - - Order and pages - - -


async def test_without_query_newest_comes_first(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: the default order is "recently added"."""
    old = await put(
        uow_factory,
        store_item,
        make_book(title="Old", published_at=NOW.replace(year=2025)),
    )
    new = await put(uow_factory, store_item, make_book(title="New", published_at=NOW))

    found = await _search(uow_factory, _filters(), _member(student))

    assert found == [new.id, old.id]


async def test_preferred_subjects_come_first_without_a_query(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: the user's subjects first, then recent."""
    mine_subject = new_id()
    other = await put(
        uow_factory, store_item, make_book(title="Newer", published_at=NOW)
    )
    mine = await put(
        uow_factory,
        store_item,
        make_book(title="Older", published_at=NOW.replace(year=2025)),
        subjects=[SubjectLink(mine_subject)],
    )
    viewer = viewer_from_actor(
        student, anonymous_cards=False, preferred_subject_ids=(mine_subject,)
    )

    found = await _search(uow_factory, _filters(), viewer)

    assert found == [mine.id, other.id]


async def test_title_hit_outranks_a_description_hit(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: relevance puts the exact title first."""
    weak = await put(
        uow_factory,
        store_item,
        make_book(title="Boshqa kitob", description="fizika haqida ham gap bor"),
    )
    strong = await put(uow_factory, store_item, make_book(title="Fizika"))

    found = await _search(uow_factory, _filters("fizika"), _member(student))

    assert found == [strong.id, weak.id]


async def test_title_and_author_sorts(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: sort=title and sort=author are alphabetical."""
    b = await put(
        uow_factory, store_item, make_book(title="B kitob", author_label="Zokirov")
    )
    a = await put(
        uow_factory, store_item, make_book(title="A kitob", author_label="Yusupov")
    )
    viewer = _member(student)

    by_title = await _search(uow_factory, _filters(sort=ItemSort.TITLE), viewer)
    by_author = await _search(uow_factory, _filters(sort=ItemSort.AUTHOR), viewer)

    assert by_title == [a.id, b.id]
    assert by_author == [a.id, b.id]


async def test_pages_do_not_overlap_or_skip(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: walking limit/offset visits every item exactly once."""
    stored = [
        await put(uow_factory, store_item, make_book(title=f"Kitob {n}"))
        for n in range(5)
    ]
    viewer = _member(student)
    seen: list[UUID] = []

    for offset in (0, 2, 4):
        seen += await _search(
            uow_factory, _filters(sort=ItemSort.TITLE), viewer, limit=2, offset=offset
        )

    assert seen == [item.id for item in stored]


# - - - Counts and lists - - -


async def test_subject_counts_only_count_listed_items(
    uow_factory: UowFactory, store_item: StoreItem, student: Actor
) -> None:
    """LIB-1: held, hidden and unpublished items are not in the counts."""
    subject = new_id()
    link = [SubjectLink(subject)]
    await put(uow_factory, store_item, make_book(title="Bir"), subjects=link)
    await put(uow_factory, store_item, make_material(title="Ikki"), subjects=link)
    await put(
        uow_factory,
        store_item,
        make_book(title="Yashirin", visibility=Visibility.HIDDEN),
        subjects=link,
    )
    await put(
        uow_factory,
        store_item,
        make_material(title="Ushlangan", status=ItemStatus.HELD),
        subjects=link,
    )
    await put(
        uow_factory,
        store_item,
        make_book(title="Olingan", status=ItemStatus.UNPUBLISHED),
        subjects=link,
    )

    async with uow_factory() as uow:
        member = await uow.items.subject_counts(_member(student))
        visitor = await uow.items.subject_counts(ANON)

    assert member == {subject: 2}
    assert visitor == {}


async def test_book_table_lists_every_status_and_filters(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-3: the librarian's table has drafts and published books, not materials."""
    draft = await put(
        uow_factory, store_item, make_book(title="Qoralama", status=ItemStatus.DRAFT)
    )
    live = await put(uow_factory, store_item, make_book(title="Nashr"))
    await put(uow_factory, store_item, make_material(title="Konspekt"))

    async with uow_factory() as uow:
        everything = await uow.items.list_books(
            query=None, status=None, limit=10, offset=0
        )
        drafts = await uow.items.list_books(
            query=None, status=ItemStatus.DRAFT, limit=10, offset=0
        )
        by_text = await uow.items.list_books(
            query="nash", status=None, limit=10, offset=0
        )

    assert set(everything) == {draft.id, live.id}
    assert drafts == [draft.id]
    assert by_text == [live.id]


async def test_sitemap_lists_only_public_published_slugs(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-14: lyceum, held and external items are not in the sitemap."""
    public = await put(
        uow_factory,
        store_item,
        make_book(
            title="Ochiq", visibility=Visibility.PUBLIC, rights=Rights.PUBLIC_DOMAIN
        ),
    )
    await put(uow_factory, store_item, make_book(title="Yopiq"))
    await put(
        uow_factory,
        store_item,
        make_book(
            title="Olingan",
            visibility=Visibility.PUBLIC,
            rights=Rights.PUBLIC_DOMAIN,
            status=ItemStatus.UNPUBLISHED,
        ),
    )

    async with uow_factory() as uow:
        entries = await uow.items.sitemap_entries(limit=100)

    assert [slug for slug, _ in entries] == [public.slug]

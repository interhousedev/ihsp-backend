"""In-item text search: indexing pages with boxes, search, OCR items, backfill."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemLanguage, TextStatus
from app.modules.library.domain.errors import TextUnavailableError
from app.modules.library.infrastructure.orm import ItemPage
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.contracts.files import PageLayout, TextBox
from app.shared.ids import new_id
from tests.factories.library import make_book
from tests.fakes.library.catalogue_files import FakeScanFilesApi
from tests.fakes.tasks import FakeTaskKicker
from tests.library.catalogue.helpers import put

import pytest
from sqlalchemy import update

StoreItem = Callable[[Item], Awaitable[Item]]
PAGES = ["Newton's laws of motion.", "Force equals mass times acceleration."]


def _pending(file_id: UUID, language: ItemLanguage = ItemLanguage.EN) -> Item:
    book = make_book(language=language)
    book.files[0].file_id = file_id
    book.files[0].text_status = TextStatus.PENDING
    book.files[0].pages = None
    return book


def _layout(page: int, text: str, source: str) -> PageLayout:
    boxes, cursor = [], 0
    for index, word in enumerate(text.split()):
        at = text.index(word, cursor)
        cursor = at + len(word)
        boxes.append(TextBox(at, cursor, 0.1 * index, 0.2, 0.08, 0.03))
    return PageLayout(page, source, tuple(boxes))


async def _index(
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeScanFilesApi,
    *,
    pages: list[str],
    source: str,
    language: ItemLanguage = ItemLanguage.EN,
) -> Item:
    file_id = files_api.add_file(owner_id=new_id(), pages=pages)
    files_api.layouts[file_id] = {
        n: _layout(n, text, source) for n, text in enumerate(pages, start=1)
    }
    book = await put(library.core.uow_factory, store_item, _pending(file_id, language))
    await library.catalogue.process_item_file.execute(book.id, file_id)
    return book


async def test_indexing_maps_text_to_pages_and_boxes(
    library: LibraryServices, store_item: StoreItem, files_api: FakeScanFilesApi
) -> None:
    """The job stores per-page text with source and word boxes."""
    book = await _index(library, store_item, files_api, pages=PAGES, source="ocr")

    async with library.core.uow_factory() as uow:
        stored = await uow.pages.pages(book.id, book.files[0].file_id, 1, 2)

    assert [p.page for p in stored] == [1, 2]
    assert {p.source for p in stored} == {"ocr"}
    assert [PAGES[1][b.start : b.end] for b in stored[1].boxes][:2] == [
        "Force",
        "equals",
    ]


async def test_search_returns_page_snippet_and_positions(
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeScanFilesApi,
    student: Actor,
) -> None:
    """A text-layer item: page, snippet, offsets and boxes of the hit."""
    book = await _index(
        library, store_item, files_api, pages=PAGES, source="text_layer"
    )

    result = await library.catalogue.search_item_text.execute(
        student, book.id, "ACCELERATION"
    )

    [hit] = result.hits
    assert hit.page == 2
    assert hit.snippet.match == "acceleration."
    assert hit.snippet.pre.endswith("mass times")
    assert PAGES[1][hit.start : hit.end] == "acceleration."
    assert [(b.x, b.y) for b in hit.boxes] == [(0.4, 0.2)]
    assert hit.source == "text_layer"


async def test_search_ocr_item(
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeScanFilesApi,
    student: Actor,
) -> None:
    """An OCR item is searched the same way and reports its source."""
    pages = ["Ўзбекистон тарихи ва маданияти", "Ватан ёки ўлим — қасамёд қилинди"]
    book = await _index(
        library,
        store_item,
        files_api,
        pages=pages,
        source="ocr",
        language=ItemLanguage.UZ_CYRL,
    )

    latin = await library.catalogue.search_item_text.execute(
        student, book.id, "o'zbekiston"
    )

    assert [(h.page, h.source) for h in latin.hits] == [(1, "ocr")]
    assert latin.hits[0].boxes


async def test_search_guards(
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeScanFilesApi,
    student: Actor,
) -> None:
    """A one-letter query is invalid; text that is not ready is unavailable."""
    book = await _index(library, store_item, files_api, pages=PAGES, source="ocr")
    scan = await put(
        library.core.uow_factory,
        store_item,
        make_book(text_status=TextStatus.NO_TEXT),
    )

    with pytest.raises(ValidationFailedError):
        await library.catalogue.search_item_text.execute(student, book.id, "a")
    with pytest.raises(TextUnavailableError):
        await library.catalogue.search_item_text.execute(student, scan.id, "force")


async def test_backfill_queues_stale_files_and_reindex_fills_them(
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeScanFilesApi,
    kicker: FakeTaskKicker,
) -> None:
    """Old rows (no folded text) are kicked once; reindexing gives them boxes."""
    book = await _index(library, store_item, files_api, pages=PAGES, source="ocr")
    file_id = book.files[0].file_id
    async with library.core.uow_factory() as uow:
        await uow.session.execute(  # type: ignore[attr-defined]
            update(ItemPage).values(text_fold=None, boxes=None, source="text_layer")
        )
        await uow.commit()

    kicked = await library.catalogue.backfill_item_pages.execute()
    done = await library.catalogue.reindex_item_pages.execute(book.id, file_id)

    assert kicked >= 1 and done
    assert (
        "library.reindex_item_pages",
        {"item_id": str(book.id), "file_id": str(file_id)},
    ) in kicker.calls
    async with library.core.uow_factory() as uow:
        stored = await uow.pages.pages(book.id, file_id, 1, 2)
    assert stored[0].source == "ocr" and stored[0].boxes
    assert await library.catalogue.backfill_item_pages.execute() == 0

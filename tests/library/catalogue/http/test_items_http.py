"""LIB-1, LIB-3, LIB-7, LIB-12: the catalogue endpoints and their JSON shapes."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.entities import Item, SubjectLink
from app.modules.library.domain.enums import (
    ItemStatus,
    Rights,
    TextStatus,
    Visibility,
)
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.library import make_book, make_external, make_material
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.fakes.library.files import FakeFilesApi
from tests.library.catalogue.helpers import put

import pytest
from httpx import AsyncClient

Api = Callable[..., Awaitable[AsyncClient]]
StoreItem = Callable[[Item], Awaitable[Item]]
CARD_KEYS = {
    "id", "slug", "kind", "type", "title", "author_label", "language",
    "year_published", "cover_url", "description_excerpt", "subjects",
    "years_of_study", "has_text", "page_count", "shelf_state",
    "progress_percent", "snippet", "snippet_page", "tag",
}  # fmt: skip


async def test_list_has_the_page_shape_and_card_fields_of_a_book(
    api: Api,
    library: LibraryServices,
    store_item: StoreItem,
    academic: FakeAcademicDirectory,
    student: Actor,
) -> None:
    """LIB-7: `{items, next_cursor}`; a book card has `tag` and `book`, nothing else."""
    physics = academic.add_subject(new_id(), "Physics")
    await put(
        library.core.uow_factory,
        store_item,
        make_book(title="Fizika 10"),
        subjects=[SubjectLink(physics)],
    )
    client = await api(student)

    response = await client.get("/v1/library/items")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "next_cursor"} and body["next_cursor"] is None
    card = body["items"][0]
    assert set(card) == CARD_KEYS | {"book"}
    assert card["tag"] == {"source": "book", "label": "Library book"}
    assert card["subjects"] == [{"id": str(physics), "name": "Physics"}]
    assert card["book"] == {
        "rights": "official",
        "licence": None,
        "download_allowed": False,
    }
    assert card["snippet"] is None and card["shelf_state"] is None


async def test_material_and_external_cards_carry_their_block(
    api: Api, library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-12: `material` for materials, `external` for UniLibrary records."""
    uow_factory = library.core.uow_factory
    await put(uow_factory, store_item, make_material(title="Konspekt"))
    await put(uow_factory, store_item, make_external(title="Elektronika"))
    client = await api(student)

    cards = {
        c["title"]: c for c in (await client.get("/v1/library/items")).json()["items"]
    }

    assert cards["Konspekt"]["material"] == {
        "uploader_name": "Aziza K.",
        "uploader_cohort": "2025",
        "uploader_role": "student",
    }
    assert "book" not in cards["Konspekt"] and "external" not in cards["Konspekt"]
    external = cards["Elektronika"]["external"]
    assert external["source"] == "unilibrary" and external["category"] == 1
    assert external["view_url"] == "https://unilibrary.uz/literature/355186"
    assert external["gone"] is False and external["access"] == "partial"
    assert cards["Elektronika"]["tag"]["source"] == "unilibrary"


async def test_visitor_sees_public_books_only(
    api: Api, library: LibraryServices, store_item: StoreItem
) -> None:
    """LIB-1: anonymous access is limited to public items."""
    uow_factory = library.core.uow_factory
    await put(
        uow_factory,
        store_item,
        make_book(
            title="Open",
            visibility=Visibility.PUBLIC,
            rights=Rights.PUBLIC_DOMAIN,
        ),
    )
    await put(uow_factory, store_item, make_book(title="Closed"))
    client = await api(None)

    titles = [
        c["title"] for c in (await client.get("/v1/library/items")).json()["items"]
    ]

    assert titles == ["Open"]


@pytest.mark.parametrize(
    "query",
    [
        "limit=1000",
        "limit=0",
        "shelf=maybe",
        "source=cloud",
        "year_of_study=0",
        "sort=best",
    ],
)
async def test_bad_query_parameters_are_rejected(
    api: Api, student: Actor, query: str
) -> None:
    """LIB-7: validation errors are 422."""
    client = await api(student)

    response = await client.get(f"/v1/library/items?{query}")

    assert response.status_code == 422


async def test_filters_arrive_from_the_query_string(
    api: Api, library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: `has_text`, `type`, `language`, `sort` and `limit` reach the search."""
    uow_factory = library.core.uow_factory
    await put(uow_factory, store_item, make_book(title="B kitob"))
    await put(uow_factory, store_item, make_book(title="A kitob"))
    client = await api(student)

    response = await client.get(
        "/v1/library/items?has_text=true&type=textbook&language=uz&sort=title&limit=1"
    )

    body = response.json()
    assert [c["title"] for c in body["items"]] == ["A kitob"]
    assert body["next_cursor"] is not None
    second = await client.get(
        f"/v1/library/items?sort=title&limit=1&cursor={body['next_cursor']}"
    )
    assert [c["title"] for c in second.json()["items"]] == ["B kitob"]


# - - - Item page - - -


async def test_item_detail_shape_for_a_book(
    api: Api, library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-3: detail = card + status, files, topics, lists, `can`, rights box."""
    book = await put(
        library.core.uow_factory,
        store_item,
        make_book(title="Fizika 10"),
    )
    client = await api(student)

    by_slug = await client.get(f"/v1/library/items/{book.slug}")
    by_id = await client.get(f"/v1/library/items/{book.id}")

    assert by_slug.status_code == 200 and by_slug.json() == by_id.json()
    body = by_slug.json()
    assert set(body) == CARD_KEYS | {
        "book", "status", "status_reason", "status_note", "visibility", "subtitle",
        "description", "publisher", "isbn", "files", "topics", "lists", "can",
        "rights_box", "progress", "tags",
    }  # fmt: skip
    assert body["status"] == "published" and body["visibility"] == "lyceum"
    assert body["files"][0]["format"] == "pdf" and body["files"][0]["toc"] == []
    assert set(body["files"][0]) == {
        "id", "format", "is_primary", "pages", "byte_size", "readable",
        "text_status", "toc",
    }  # fmt: skip
    assert body["can"] == {
        "read": True, "download": False, "add_to_notebook": True,
        "report": True, "edit": False,
    }  # fmt: skip
    assert set(body["rights_box"]) == {"text", "attribution", "download_allowed"}


async def test_hidden_items_are_a_404_problem_never_a_403(
    api: Api, library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-1: held and unpublished items do not exist for students (IDOR)."""
    uow_factory = library.core.uow_factory
    held = await put(uow_factory, store_item, make_material(status=ItemStatus.HELD))
    gone = await put(uow_factory, store_item, make_book(status=ItemStatus.UNPUBLISHED))
    client = await api(student)

    for item in (held, gone):
        for ref in (str(item.id), item.slug):
            response = await client.get(f"/v1/library/items/{ref}")
            assert response.status_code == 404
            assert response.json()["type"] == "library/not-found"
            assert response.headers["content-type"].startswith(
                "application/problem+json"
            )


async def test_visitor_gets_404_for_a_lyceum_item(
    api: Api, library: LibraryServices, store_item: StoreItem
) -> None:
    """LIB-1: no login, no lyceum items."""
    book = await put(library.core.uow_factory, store_item, make_book())
    client = await api(None)

    response = await client.get(f"/v1/library/items/{book.id}")

    assert response.status_code == 404


async def test_owner_sees_the_status_of_their_own_draft(
    api: Api, library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-1: owners open their own drafts and may edit them."""
    draft = await put(
        library.core.uow_factory,
        store_item,
        make_material(status=ItemStatus.DRAFT, uploader_id=student.user_id),
    )
    client = await api(student)

    body = (await client.get(f"/v1/library/items/{draft.id}")).json()

    assert body["status"] == "draft" and body["can"]["edit"] is True


# - - - Files and text - - -


async def test_file_url_endpoint(
    api: Api,
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeFilesApi,
    student: Actor,
) -> None:
    """LIB-3: `{url, expires_at, content_type, byte_size}` for 15 minutes."""
    file_id = files_api.add_file(owner_id=new_id())
    book = await put(
        library.core.uow_factory,
        store_item,
        make_book(file_id=file_id),
    )
    client = await api(student)

    response = await client.get(
        f"/v1/library/items/{book.id}/files/{file_id}/url?inline=1"
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"url", "expires_at", "content_type", "byte_size"}
    assert body["content_type"] == "application/pdf" and "inline=True" in body["url"]
    assert body["expires_at"].startswith("2026-10-06T09:15:00")


async def test_file_url_errors(
    api: Api,
    library: LibraryServices,
    store_item: StoreItem,
    files_api: FakeFilesApi,
    student: Actor,
) -> None:
    """LIB-3, LIB-12: 403 for no-download, 409 for UniLibrary, 404 for unknown."""
    uow_factory = library.core.uow_factory
    file_id = files_api.add_file(owner_id=new_id())
    book = await put(uow_factory, store_item, make_book(file_id=file_id))
    record = await put(uow_factory, store_item, make_external())
    client = await api(student)

    download = await client.get(f"/v1/library/items/{book.id}/files/{file_id}/url")
    external = await client.get(
        f"/v1/library/items/{record.id}/files/{new_id()}/url?inline=1"
    )
    unknown = await client.get(
        f"/v1/library/items/{book.id}/files/{new_id()}/url?inline=1"
    )

    assert (download.status_code, download.json()["type"]) == (
        403,
        "library/download-not-allowed",
    )
    assert (external.status_code, external.json()["type"]) == (
        409,
        "library/not-supported",
    )
    assert unknown.status_code == 404


async def test_text_endpoint(
    api: Api, library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: `{pages: [{page, text}]}` for a range; 422 for a bad range."""
    book = await put(
        library.core.uow_factory,
        store_item,
        make_book(),
        pages=["one", "two", "three"],
    )
    client = await api(student)

    ok = await client.get(f"/v1/library/items/{book.id}/text?page_from=2&page_to=3")
    bad = await client.get(f"/v1/library/items/{book.id}/text?page_from=3&page_to=1")

    assert ok.json() == {
        "pages": [{"page": 2, "text": "two"}, {"page": 3, "text": "three"}]
    }
    assert bad.status_code == 422


async def test_text_of_a_scan_is_a_409(
    api: Api, library: LibraryServices, store_item: StoreItem, student: Actor
) -> None:
    """LIB-7: `409 library/text-unavailable`."""
    scan = await put(
        library.core.uow_factory,
        store_item,
        make_book(text_status=TextStatus.NO_TEXT),
    )
    client = await api(student)

    response = await client.get(f"/v1/library/items/{scan.id}/text")

    assert response.status_code == 409
    assert response.json()["type"] == "library/text-unavailable"


# - - - Subjects - - -


async def test_subjects_endpoint_with_and_without_all(
    api: Api,
    library: LibraryServices,
    store_item: StoreItem,
    librarian: Actor,
    student: Actor,
) -> None:
    """LIB-1: `[{id, name, item_count}]`; `?all=1` adds empty subjects."""
    physics = (
        await library.taxonomy.create_subject.execute(librarian, name={"en": "Physics"})
    ).id
    astronomy = (
        await library.taxonomy.create_subject.execute(
            librarian, name={"en": "Astronomy"}
        )
    ).id
    await put(
        library.core.uow_factory,
        store_item,
        make_book(),
        subjects=[SubjectLink(physics)],
    )
    client = await api(student)

    shelves = (await client.get("/v1/library/subjects")).json()
    everything = (await client.get("/v1/library/subjects?all=1")).json()

    assert shelves == [
        {
            "id": str(physics),
            "name": "Physics",
            "item_count": 1,
            "parent_id": None,
            "code": None,
        }
    ]
    assert {s["id"]: s["item_count"] for s in everything} == {
        str(physics): 1,
        str(astronomy): 0,
    }
    assert UUID(everything[0]["id"])

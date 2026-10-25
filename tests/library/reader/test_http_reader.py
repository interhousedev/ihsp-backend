"""LIB-7, LIB-8, LIB-6: My library over HTTP: shapes, status codes, privacy."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.interfaces.http.dependencies import get_actor, get_optional_actor
from app.interfaces.http.v1.library.reader import ROUTERS as READER_ROUTERS
from app.modules.library.domain.entities import Item
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.conftest import HttpClientFactory

import pytest
from httpx import AsyncClient

Api = Callable[[Actor | None], Awaitable[AsyncClient]]


@pytest.fixture
def api(http_client: HttpClientFactory, library: LibraryServices) -> Api:
    """`await api(actor)` is a client of the reader routes logged in as the actor."""

    async def build(actor: Actor | None = None) -> AsyncClient:
        overrides: dict[Callable[..., Any], Callable[..., Any]] = {}
        if actor is not None:
            overrides = {get_actor: lambda: actor, get_optional_actor: lambda: actor}
        return await http_client(READER_ROUTERS, overrides, library=library)

    return build


def annotation(book: Item, **changes: Any) -> dict[str, Any]:
    """A valid `AnnotationInput` for the book."""
    body: dict[str, Any] = {
        "client_id": str(new_id()),
        "item_id": str(book.id),
        "file_id": str(book.files[0].file_id),
        "kind": "highlight",
        "locator": {"page": 3},
        "quote": "F = ma",
        "color": "yellow",
    }
    return body | changes


async def test_shelf_roundtrip_and_my_library(
    api: Api, student: Actor, book: Item
) -> None:
    """LIB-7: put, list, count and remove; `continue` is the wire name."""
    client = await api(student)

    put = await client.put(f"/v1/me/library/shelf/{book.id}", json={"state": "reading"})
    shelf = await client.get("/v1/me/library/shelf")
    home = await client.get("/v1/me/library")
    removed = await client.delete(f"/v1/me/library/shelf/{book.id}")

    assert put.status_code == 200 and put.json()["state"] == "reading"
    assert [e["item"]["id"] for e in shelf.json()["items"]] == [str(book.id)]
    assert shelf.json()["items"][0]["item"]["shelf_state"] == "reading"
    assert home.json()["shelf_counts"]["reading"] == 1
    assert home.json()["continue"] == [] and "offline" in home.json()
    assert removed.status_code == 204


async def test_progress_is_saved_and_unknown_items_are_404(
    api: Api, student: Actor, book: Item
) -> None:
    """LIB-6: `204` for a saved position; an item the caller cannot see is 404."""
    client = await api(student)
    body = {
        "file_id": str(book.files[0].file_id),
        "locator": {"page": 5},
        "percent": 4.2,
        "client_ts": "2026-10-06T09:00:00Z",
    }

    saved = await client.put(f"/v1/me/library/progress/{book.id}", json=body)
    missing = await client.put(f"/v1/me/library/progress/{new_id()}", json=body)

    assert saved.status_code == 204
    assert missing.status_code == 404


async def test_annotations_are_idempotent_private_and_exportable(
    api: Api, student: Actor, other_student: Actor, book: Item
) -> None:
    """LIB-8: same `client_id` twice is one note; nobody else sees or edits it."""
    mine, theirs = await api(student), await api(other_student)
    body = annotation(book)

    first = await mine.post("/v1/me/library/annotations", json=body)
    again = await mine.post("/v1/me/library/annotations", json=body)
    note_id = first.json()["id"]
    patched = await mine.patch(
        f"/v1/me/library/annotations/{note_id}", json={"note": "check units"}
    )
    listed = await mine.get(
        "/v1/me/library/annotations", params={"item_id": str(book.id)}
    )
    foreign = await theirs.get("/v1/me/library/annotations")
    stolen = await theirs.patch(
        f"/v1/me/library/annotations/{note_id}", json={"note": "mine now"}
    )
    export = await mine.get("/v1/me/library/annotations/export")
    deleted = await mine.delete(f"/v1/me/library/annotations/{note_id}")

    assert first.status_code == 201 and again.json()["id"] == note_id
    assert patched.json()["note"] == "check units"
    assert [a["id"] for a in listed.json()["items"]] == [note_id]
    assert foreign.json()["items"] == []
    assert stolen.status_code == 404
    assert "F = ma" in export.text and export.headers["content-type"].startswith(
        "text/markdown"
    )
    assert deleted.status_code == 204


async def test_sync_applies_upserts_and_deletes(
    api: Api, student: Actor, book: Item
) -> None:
    """LIB-9: a device's queue is applied in one call and the state comes back."""
    client = await api(student)
    keep, drop = annotation(book), annotation(book, quote="drop me")
    await client.post("/v1/me/library/annotations", json=drop)

    synced = await client.post(
        "/v1/me/library/annotations/sync",
        json={"upserts": [keep], "deletes": [drop["client_id"]]},
    )
    listed = await client.get("/v1/me/library/annotations")

    assert synced.status_code == 200
    assert [a["client_id"] for a in synced.json()["items"]] == [keep["client_id"]]
    assert [a["client_id"] for a in listed.json()["items"]] == [keep["client_id"]]


async def test_everything_needs_a_login(api: Api) -> None:
    """LIB-16: no token, no shelf, no notes."""
    client = await api(None)

    for path in (
        "/v1/me/library",
        "/v1/me/library/shelf",
        "/v1/me/library/annotations",
    ):
        assert (await client.get(path)).status_code == 401

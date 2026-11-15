"""Page markup: shape rules, storage per user and item, HTTP privacy (IDOR)."""

import datetime as dt
from collections.abc import Callable
from typing import Any

from app.interfaces.http.dependencies import get_actor, get_optional_actor
from app.interfaces.http.v1.library.reader import ROUTERS as READER_ROUTERS
from app.modules.library.domain.entities import Item
from app.modules.library.domain.reader_errors import InvalidMarkupError
from app.modules.library.domain.reader_markup import (
    Markup,
    pages_to_dict,
    parse_pages,
    parse_shape,
    shape_to_dict,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.conftest import HttpClientFactory
from tests.library.reader.test_http_reader import Api

import pytest
from httpx import AsyncClient


@pytest.fixture
def api(http_client: HttpClientFactory, library: LibraryServices) -> Api:
    """`await api(actor)` is a client of the reader routes logged in as the actor."""

    async def build(actor: Actor | None = None) -> AsyncClient:
        overrides: dict[Callable[..., Any], Callable[..., Any]] = {}
        if actor is not None:
            overrides = {get_actor: lambda: actor, get_optional_actor: lambda: actor}
        return await http_client(READER_ROUTERS, overrides, library=library)

    return build


NOW = dt.datetime(2026, 11, 15, 9, 0, tzinfo=dt.UTC)


def shape(**changes: Any) -> dict[str, Any]:
    """A valid pen stroke."""
    body: dict[str, Any] = {
        "id": "s1",
        "tool": "pen",
        "color": "#FF0000",
        "width": 0.004,
        "points": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]],
    }
    return body | changes


# - - - Rules - - -


def test_shape_roundtrips_through_its_json_form() -> None:
    """A parsed shape serializes back to an equal dict (colour lower-cased)."""
    parsed = parse_shape(shape())
    assert shape_to_dict(parsed) == shape(color="#ff0000")
    assert parse_shape(shape_to_dict(parsed)) == parsed


def test_pages_roundtrip_and_drop_empty_pages() -> None:
    """Pages keep their shapes in order; an empty page is not stored."""
    raw = {"2": [shape(id="a"), shape(id="b", tool="highlighter")], "5": []}
    pages = parse_pages(raw)
    assert list(pages) == [2]
    assert [s.id for s in pages[2]] == ["a", "b"]
    assert pages_to_dict(pages) == {
        "2": [shape_to_dict(s) for s in pages[2]],
    }


@pytest.mark.parametrize("tool", ["rect", "ellipse", "line", "arrow"])
def test_figures_need_exactly_two_points(tool: str) -> None:
    """A figure is two corners or ends; three points are refused."""
    parse_shape(shape(tool=tool, points=[[0.1, 0.1], [0.9, 0.9]]))
    with pytest.raises(InvalidMarkupError):
        parse_shape(shape(tool=tool))


@pytest.mark.parametrize(
    "changes",
    [
        {"tool": "laser"},
        {"color": "red"},
        {"color": "#12345"},
        {"width": 0},
        {"width": 5},
        {"width": True},
        {"points": []},
        {"points": [[0.1]]},
        {"points": [[1.5, 0.2]]},
        {"points": [[-0.1, 0.2]]},
        {"points": [["a", 0.2]]},
        {"id": ""},
        {"id": "x" * 65},
    ],
)
def test_bad_shapes_are_refused(changes: dict[str, Any]) -> None:
    """Out-of-range numbers, bad colours, tools and ids are all invalid."""
    with pytest.raises(InvalidMarkupError):
        parse_shape(shape(**changes))


def test_bad_pages_are_refused() -> None:
    """Page keys are positive integers, ids are unique on a page, a page is bounded."""
    for pages in (
        {"zero": [shape()]},
        {"0": [shape()]},
        {"1": [shape(), shape()]},
        {"1": [shape(id=str(n)) for n in range(501)]},
    ):
        with pytest.raises(InvalidMarkupError):
            parse_pages(pages)


# - - - Storage - - -


def markup(user: Any, item: Any, *, page: int = 1, ident: str = "a") -> Markup:
    """A one-shape document."""
    return Markup(
        user_id=user,
        item_id=item,
        file_id=new_id(),
        pages=parse_pages({str(page): [shape(id=ident)]}),
        updated_at=NOW,
    )


async def test_markup_is_saved_replaced_and_scoped_to_the_user(
    uow_factory: UowFactory,
) -> None:
    """Save/load per user: a second save replaces, another user sees nothing."""
    user, stranger, item = new_id(), new_id(), new_id()
    async with uow_factory() as uow:
        await uow.markup.save(markup(user, item, page=1))
        await uow.markup.save(markup(user, item, page=4, ident="b"))
        await uow.markup.save(markup(stranger, item, page=9, ident="z"))

        mine = await uow.markup.get(user, item)
        theirs = await uow.markup.get(stranger, item)
        other_item = await uow.markup.get(user, new_id())

    assert mine is not None and list(mine.pages) == [4]
    assert mine.pages[4][0].points[1] == (0.3, 0.4)
    assert theirs is not None and list(theirs.pages) == [9]
    assert other_item is None


async def test_delete_removes_one_item_and_delete_all_the_users_rows(
    uow_factory: UowFactory,
) -> None:
    """Clearing one item keeps the others; account closure clears the rest."""
    user, other = new_id(), new_id()
    first, second = new_id(), new_id()
    async with uow_factory() as uow:
        await uow.markup.save(markup(user, first))
        await uow.markup.save(markup(user, second))
        await uow.markup.save(markup(other, first))

        await uow.markup.delete(user, first)
        assert await uow.markup.get(user, first) is None
        assert await uow.markup.delete_all(user) == 1
        assert await uow.markup.get(other, first) is not None


# - - - HTTP - - -


def body(book: Item, **pages: Any) -> dict[str, Any]:
    """A `MarkupBody` for the book."""
    return {
        "file_id": str(book.files[0].file_id),
        "pages": pages or {"3": [shape()]},
    }


async def test_markup_roundtrip_over_http(api: Api, student: Actor, book: Item) -> None:
    """PUT then GET returns the same shapes; no markup is an empty document."""
    client = await api(student)
    empty = await client.get(f"/v1/me/library/markup/{book.id}")
    saved = await client.put(f"/v1/me/library/markup/{book.id}", json=body(book))
    loaded = await client.get(f"/v1/me/library/markup/{book.id}")

    assert empty.status_code == 200 and empty.json()["pages"] == {}
    assert saved.status_code == 200
    assert loaded.json()["pages"]["3"][0]["id"] == "s1"
    assert loaded.json()["pages"]["3"][0]["color"] == "#ff0000"
    assert loaded.json()["file_id"] == str(book.files[0].file_id)


async def test_saving_no_shapes_clears_the_markup(
    api: Api, student: Actor, book: Item
) -> None:
    """An empty PUT removes the stored markup."""
    client = await api(student)
    await client.put(f"/v1/me/library/markup/{book.id}", json=body(book))
    cleared = await client.put(
        f"/v1/me/library/markup/{book.id}", json=body(book, **{"3": []})
    )
    loaded = await client.get(f"/v1/me/library/markup/{book.id}")

    assert cleared.status_code == 200
    assert loaded.json()["pages"] == {} and loaded.json()["file_id"] is None


async def test_markup_is_private_idor(
    api: Api, student: Actor, other_student: Actor, book: Item
) -> None:
    """IDOR: another user never reads or overwrites my markup; ids give no access."""
    mine, theirs = await api(student), await api(other_student)
    await mine.put(f"/v1/me/library/markup/{book.id}", json=body(book))

    seen = await theirs.get(f"/v1/me/library/markup/{book.id}")
    await theirs.put(
        f"/v1/me/library/markup/{book.id}",
        json=body(book, **{"7": [shape(id="evil")]}),
    )
    still_mine = await mine.get(f"/v1/me/library/markup/{book.id}")
    theirs_now = await theirs.get(f"/v1/me/library/markup/{book.id}")

    assert seen.json()["pages"] == {}
    assert list(still_mine.json()["pages"]) == ["3"]
    assert list(theirs_now.json()["pages"]) == ["7"]


async def test_markup_rejects_hidden_items_foreign_files_and_bad_shapes(
    api: Api, student: Actor, book: Item, hidden: Item
) -> None:
    """A closed item is 404, a file of another item and a bad shape are 4xx."""
    client = await api(student)
    closed = await client.put(f"/v1/me/library/markup/{hidden.id}", json=body(hidden))
    missing = await client.get(f"/v1/me/library/markup/{new_id()}")
    foreign = await client.put(
        f"/v1/me/library/markup/{book.id}",
        json=body(book) | {"file_id": str(new_id())},
    )
    invalid = await client.put(
        f"/v1/me/library/markup/{book.id}",
        json=body(book, **{"1": [shape(points=[[2, 2]])]}),
    )

    assert closed.status_code == 404 and missing.status_code == 404
    assert foreign.status_code in (400, 422)
    assert invalid.status_code in (400, 422)


def test_total_points_are_capped() -> None:
    from app.modules.library.domain import reader_markup as rm
    from app.modules.library.domain.reader_errors import InvalidMarkupError

    shape = lambda i: {  # noqa: E731
        "id": f"s{i}",
        "tool": "pen",
        "color": "#000000",
        "width": 0.01,
        "points": [[0.1, 0.1]] * rm.MAX_POINTS,
    }
    pages = {str(p): [shape(0)] for p in range(1, 102)}
    with pytest.raises(InvalidMarkupError):
        rm.parse_pages(pages)

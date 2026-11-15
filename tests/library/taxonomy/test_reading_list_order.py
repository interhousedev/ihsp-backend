"""Pinning and the manual order of reading lists: permissions and sequence."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.errors import ListNotFoundError
from app.modules.library.domain.reading_list import reordered
from app.modules.library.domain.taxonomy_errors import ListInvalidError
from app.shared.actor import Actor
from app.shared.ids import new_id

import pytest
from httpx import AsyncClient

Api = Callable[[Actor | None], Awaitable[AsyncClient]]
BASE = "/v1/library/reading-lists"


async def _make(client: AsyncClient, title: str) -> str:
    response = await client.post(
        BASE, json={"title": title, "scope": "school", "status": "published"}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _titles(client: AsyncClient) -> list[str]:
    return [card["title"] for card in (await client.get(BASE)).json()]


def test_reordered_keeps_untouched_slots() -> None:
    """Listed ids swap inside their own slots; the others stay put."""
    a, b, c, d = (new_id() for _ in range(4))

    assert reordered([a, b, c, d], [d, b]) == [a, d, c, b]
    assert reordered([a, b, c], [c, b, a]) == [c, b, a]


def test_reordered_rejects_unknown_and_repeated_ids() -> None:
    """A foreign or doubled id is an invalid request."""
    a, b = new_id(), new_id()

    with pytest.raises(ListInvalidError):
        reordered([a, b], [a, new_id()])
    with pytest.raises(ListInvalidError):
        reordered([a, b], [a, a])


async def test_new_lists_go_last_and_librarian_reorders(
    api: Api, librarian: Actor, student: Actor
) -> None:
    """The manual order is stored and every reader sees it."""
    client = await api(librarian)
    first = await _make(client, "First")
    second = await _make(client, "Second")
    third = await _make(client, "Third")
    assert await _titles(client) == ["First", "Second", "Third"]

    moved = await client.put(f"{BASE}/order", json={"ids": [third, first, second]})

    assert moved.status_code == 204
    assert await _titles(client) == ["Third", "First", "Second"]
    assert await _titles(await api(student)) == ["Third", "First", "Second"]


async def test_pinned_lists_come_first_then_the_manual_order(
    api: Api, librarian: Actor, student: Actor
) -> None:
    """A pin lifts a list over the order; unpinning puts it back."""
    client = await api(librarian)
    await _make(client, "First")
    second = await _make(client, "Second")
    third = await _make(client, "Third")

    pinned = await client.put(f"{BASE}/{third}/pin", json={"pinned": True})
    also = await client.put(f"{BASE}/{second}/pin", json={"pinned": True})

    assert pinned.status_code == 200 and pinned.json()["pinned"] is True
    assert also.json()["pinned"] is True
    assert await _titles(await api(student)) == ["Second", "Third", "First"]

    await client.put(f"{BASE}/order", json={"ids": [third, second]})
    assert await _titles(client) == ["Third", "Second", "First"]

    unpinned = await client.put(f"{BASE}/{third}/pin", json={"pinned": False})
    assert unpinned.json()["pinned"] is False
    assert await _titles(client) == ["Second", "First", "Third"]


async def test_only_librarians_pin_or_reorder(
    api: Api, librarian: Actor, teacher: Actor, student: Actor
) -> None:
    """Teachers and students get 403; nothing changes."""
    owner = await api(librarian)
    list_id = await _make(owner, "Only")

    for actor in (teacher, student):
        client = await api(actor)
        pin = await client.put(f"{BASE}/{list_id}/pin", json={"pinned": True})
        order = await client.put(f"{BASE}/order", json={"ids": [list_id]})
        assert (pin.status_code, order.status_code) == (403, 403)

    assert (await owner.get(f"{BASE}/{list_id}")).json()["pinned"] is False
    anonymous = await (await api(None)).put(f"{BASE}/order", json={"ids": []})
    assert anonymous.status_code == 401


async def test_pin_and_order_reject_missing_lists(
    api: Api, librarian: Actor, library: object
) -> None:
    """An unknown list is 404 for a pin and 422 in an order."""
    client = await api(librarian)
    missing: UUID = new_id()

    pin = await client.put(f"{BASE}/{missing}/pin", json={"pinned": True})
    order = await client.put(f"{BASE}/order", json={"ids": [str(missing)]})

    assert pin.status_code == 404
    assert order.status_code == 422
    assert ListNotFoundError.code == "library/list-not-found"

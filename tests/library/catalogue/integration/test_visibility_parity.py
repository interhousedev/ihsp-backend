"""LIB-1: the SQL visibility of the search equals `domain.access.can_view`.

Every combination of kind, status and visibility is stored, for a stranger and for
the student who owns them; each kind of viewer must find exactly the items that
`can_view` lets them see. If the two ever drift, an item leaks (or vanishes).
"""

import itertools
from collections.abc import Awaitable, Callable
from datetime import timedelta

from app.modules.library.domain.access import can_view
from app.modules.library.domain.catalogue_search import (
    ItemFilters,
    Viewer,
    viewer_from_actor,
)
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemKind, ItemStatus, Visibility
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from tests.factories.library import NOW, make_book, make_external, make_material
from tests.library.catalogue.helpers import hit_ids, put

import pytest

StoreItem = Callable[[Item], Awaitable[Item]]


def _make(
    kind: ItemKind, status: ItemStatus, visibility: Visibility, owner: Actor | None
) -> Item:
    if kind is ItemKind.BOOK:
        item = make_book(status=status, visibility=visibility)
        if owner:
            item.owner_id = owner.user_id
    elif kind is ItemKind.MATERIAL:
        item = make_material(
            status=status,
            visibility=visibility,
            uploader_id=owner.user_id if owner else None,
        )
    else:
        item = make_external(status=status)
        assert item.external is not None
        item.external.external_id = item.id.hex[-12:]
        item.visibility = visibility
        item.owner_id = owner.user_id if owner else None
    item.title = (
        f"{kind.value} {status.value} {visibility.value} {'own' if owner else 'other'}"
    )
    item.published_at = NOW - timedelta(days=1)
    return item


@pytest.mark.parametrize("cards", [False, True])
async def test_search_and_can_view_agree_for_every_viewer(
    uow_factory: UowFactory,
    store_item: StoreItem,
    student: Actor,
    other_student: Actor,
    teacher: Actor,
    librarian: Actor,
    admin: Actor,
    cards: bool,
) -> None:
    """LIB-1: 3 kinds x 8 statuses x 3 visibilities, own and foreign."""
    stored: list[Item] = []
    for kind, status, visibility, mine in itertools.product(
        ItemKind, ItemStatus, Visibility, (True, False)
    ):
        item = _make(kind, status, visibility, student if mine else None)
        stored.append(await put(uow_factory, store_item, item))
    # the "gone" UniLibrary record is a published item with `gone_at` set
    gone = _make(ItemKind.EXTERNAL, ItemStatus.PUBLISHED, Visibility.PUBLIC, None)
    assert gone.external is not None
    gone.external.gone_at = NOW
    gone.title = "external gone public"
    stored.append(await put(uow_factory, store_item, gone))

    viewers: dict[str, Actor | None] = {
        "visitor": None,
        "owner": student,
        "stranger": other_student,
        "teacher": teacher,
        "librarian": librarian,
        "admin": admin,
    }
    for name, actor in viewers.items():
        viewer: Viewer = viewer_from_actor(actor, anonymous_cards=cards)
        async with uow_factory() as uow:
            hits = await uow.items.search(ItemFilters(), viewer, limit=500, offset=0)
        found = set(hit_ids(hits))
        expected = {i.id for i in stored if can_view(i, actor, anonymous_cards=cards)}
        leaked = [i.title for i in stored if i.id in found - expected]
        missing = [i.title for i in stored if i.id in expected - found]
        assert (leaked, missing) == ([], []), f"{name}, anonymous_cards={cards}"

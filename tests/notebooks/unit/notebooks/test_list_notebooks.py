"""NB-2: the notebook list (order, search, owner isolation, cursor paging)."""

from datetime import datetime, timedelta
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_notebooks import NotebooksLifecycleServices
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.pagination import encode_cursor
from tests.factories.notebooks import NOW, make_notebook, make_source

import pytest


async def _library(uow_factory: UowFactory, owner: UUID) -> dict[str, Notebook]:
    """Five notebooks: two pinned, three loose, one never opened."""

    def opened(minutes: int) -> datetime:
        return NOW - timedelta(minutes=minutes)

    return {
        "pin_old": await make_notebook(
            uow_factory, owner, title="Pin old", pinned=True, last_opened_at=opened(90)
        ),
        "pin_new": await make_notebook(
            uow_factory, owner, title="Pin new", pinned=True, last_opened_at=opened(30)
        ),
        "recent": await make_notebook(
            uow_factory, owner, title="Recent", last_opened_at=opened(5)
        ),
        "older": await make_notebook(
            uow_factory, owner, title="Older", last_opened_at=opened(60)
        ),
        "never": await make_notebook(uow_factory, owner, title="Never opened"),
    }


async def test_pinned_come_first_then_the_most_recently_opened(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-2: pinned first; inside a group newest open first, never opened last."""
    books = await _library(uow_factory, student.user_id)

    page = await lifecycle.list_notebooks.execute(student)

    assert [n.id for n in page.items] == [
        books[name].id for name in ("pin_new", "pin_old", "recent", "older", "never")
    ]
    assert page.next_cursor is None


async def test_only_the_students_own_live_notebooks_are_listed(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-2: another student's and deleted notebooks never show up."""
    mine = await make_notebook(uow_factory, student.user_id)
    await make_notebook(uow_factory, student.user_id, deleted_at=NOW)
    await make_notebook(uow_factory, other_student.user_id)

    page = await lifecycle.list_notebooks.execute(student)

    assert [n.id for n in page.items] == [mine.id]


async def test_search_matches_the_title_ignoring_case(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-2: `q` is a case-insensitive substring of the title; blank means all."""
    await make_notebook(uow_factory, student.user_id, title="Biology 10")
    await make_notebook(uow_factory, student.user_id, title="Chemistry")

    found = await lifecycle.list_notebooks.execute(student, "BIOLOGY")
    everything = await lifecycle.list_notebooks.execute(student, "   ")
    nothing = await lifecycle.list_notebooks.execute(student, "physics")

    assert [n.title for n in found.items] == ["Biology 10"]
    assert len(everything.items) == 2
    assert nothing.items == []


async def test_cursor_pages_walk_the_whole_list_once_in_order(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-2: pages of 2 cross the pinned/loose and opened/never-opened borders."""
    books = await _library(uow_factory, student.user_id)
    expected = [
        books[name].id for name in ("pin_new", "pin_old", "recent", "older", "never")
    ]

    first = await lifecycle.list_notebooks.execute(student, limit=2)
    second = await lifecycle.list_notebooks.execute(
        student, cursor=first.next_cursor, limit=2
    )
    third = await lifecycle.list_notebooks.execute(
        student, cursor=second.next_cursor, limit=2
    )

    assert [n.id for n in first.items] == expected[:2]
    assert first.next_cursor is not None
    assert [n.id for n in second.items] == expected[2:4]
    assert second.next_cursor is not None
    assert [n.id for n in third.items] == expected[4:]
    assert third.next_cursor is None


async def test_a_page_that_ends_exactly_at_the_last_notebook_has_no_cursor(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-2: the cursor appears only when there really is one more notebook."""
    await _library(uow_factory, student.user_id)

    page = await lifecycle.list_notebooks.execute(student, limit=5)

    assert len(page.items) == 5
    assert page.next_cursor is None


async def test_notebooks_opened_at_the_same_moment_are_paged_by_id(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-2: notebooks opened at the same moment are split by id, none repeats."""
    same = NOW - timedelta(minutes=1)
    ids = {
        (await make_notebook(uow_factory, student.user_id, last_opened_at=same)).id
        for _ in range(5)
    }

    seen: list[UUID] = []
    cursor: str | None = None
    while True:
        page = await lifecycle.list_notebooks.execute(student, cursor=cursor, limit=2)
        seen.extend(n.id for n in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert len(seen) == 5
    assert set(seen) == ids


async def test_limit_is_kept_between_1_and_100(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-2: limit 0 or negative still returns one notebook; the default is 30."""
    for _ in range(3):
        await make_notebook(uow_factory, student.user_id)

    zero = await lifecycle.list_notebooks.execute(student, limit=0)
    negative = await lifecycle.list_notebooks.execute(student, limit=-4)
    huge = await lifecycle.list_notebooks.execute(student, limit=100_000)

    assert len(zero.items) == len(negative.items) == 1
    assert len(huge.items) == 3


async def test_default_page_has_30_notebooks(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-2: without a limit the first page holds 30 notebooks."""
    for _ in range(31):
        await make_notebook(uow_factory, student.user_id)

    page = await lifecycle.list_notebooks.execute(student)

    assert len(page.items) == 30
    assert page.next_cursor is not None


@pytest.mark.parametrize(
    "cursor",
    [
        "not-a-cursor!",
        encode_cursor({"x": 1}),
        encode_cursor({"p": "yes", "o": None, "id": "x"}),
        encode_cursor({"p": False, "o": "yesterday", "id": "x"}),
        encode_cursor({"p": False, "o": None, "id": "not-a-uuid"}),
    ],
)
async def test_a_broken_cursor_is_a_validation_error(
    lifecycle: NotebooksLifecycleServices, student: Actor, cursor: str
) -> None:
    """NB-2: cursors are opaque; anything we did not issue answers 422."""
    with pytest.raises(ValidationFailedError):
        await lifecycle.list_notebooks.execute(student, cursor=cursor)


async def test_listed_notebooks_carry_their_source_counters(
    lifecycle: NotebooksLifecycleServices, uow_factory: UowFactory, student: Actor
) -> None:
    """NB-2: ready and selected counts come with each item."""
    notebook = await make_notebook(uow_factory, student.user_id)
    await make_source(uow_factory, notebook)
    await make_source(uow_factory, notebook, selected=False)

    page = await lifecycle.list_notebooks.execute(student)

    assert (page.items[0].ready_source_count, page.items[0].selected_source_count) == (
        2,
        1,
    )
    assert page.items[0].source_count == 2

"""The shared pager: slicing, clamping and the ‹ n/m › row."""

from app.interfaces.bot.utilities.pagination import pager_row, paginate
from app.shared.contracts.callbacks import PageCb


def test_paginate_slices_and_clamps() -> None:
    """Pages are 8 items; an out-of-range page is clamped."""
    items = list(range(20))

    first = paginate(items, 0)
    last = paginate(items, 99)

    assert first.items == list(range(8))
    assert first.pages == 3
    assert (last.index, last.items) == (2, [16, 17, 18, 19])
    assert paginate([], 0).pages == 1


def test_pager_row_is_hidden_for_one_page() -> None:
    """Short lists get no pager."""
    assert pager_row("hw", paginate([1, 2, 3], 0)) == []


def test_pager_row_points_to_neighbours() -> None:
    """The middle button shows n/m; arrows stay inside the range."""
    row = pager_row("hw", paginate(list(range(20)), 0))

    assert row[0]["callback_data"] == PageCb(kind="hw", page=0).pack()
    assert row[1]["text"] == "1/3"
    assert row[2]["callback_data"] == PageCb(kind="hw", page=1).pack()

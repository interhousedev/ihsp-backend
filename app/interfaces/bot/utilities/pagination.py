"""One paging scheme for every long list: slice, and the ‹ n/m › row."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.interfaces.bot.utilities.markup import Button, cb_button, none_button
from app.shared.contracts.callbacks import PageCb

PAGE_SIZE = 8


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One slice of a list with its position."""

    items: list[T]
    index: int
    pages: int


def paginate[T](  # noqa: D103
    items: Sequence[T], index: int, size: int = PAGE_SIZE
) -> Page[T]:
    """Return the slice for page ``index`` (clamped into range)."""
    pages = max(1, -(-len(items) // size))
    index = min(max(index, 0), pages - 1)
    return Page(list(items[index * size : (index + 1) * size]), index, pages)


def pager_row(kind: str, page: Page[Any]) -> list[Button]:
    """Return the ‹ n/m › row, or an empty row when one page is enough."""
    if page.pages <= 1:
        return []
    prev_page = max(page.index - 1, 0)
    next_page = min(page.index + 1, page.pages - 1)
    return [
        cb_button("‹", PageCb(kind=kind, page=prev_page)),
        none_button(f"{page.index + 1}/{page.pages}"),
        cb_button("›", PageCb(kind=kind, page=next_page)),
    ]

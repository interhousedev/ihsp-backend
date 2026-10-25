"""A page of items with an opaque cursor for the next page."""

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Paged(Generic[T]):
    """`items` and the cursor of the following page (None on the last page)."""

    items: list[T]
    next_cursor: str | None = None

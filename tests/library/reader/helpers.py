"""Small helpers shared by the reader state tests."""

from collections.abc import Awaitable, Callable

from app.modules.library.domain.entities import Item

StoreItem = Callable[[Item], Awaitable[Item]]

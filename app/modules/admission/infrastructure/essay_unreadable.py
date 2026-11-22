"""Sealed rows whose key is lost or changed are skipped by readers, with a warning."""

from collections.abc import Awaitable, Callable, Iterable
from typing import Final, TypeVar

from app.modules.admission.domain.errors import EssayKeyUnavailableError

import structlog

log = structlog.get_logger(__name__)

UNREADABLE: Final = (ValueError, EssayKeyUnavailableError)
"""A blob that no longer opens (`EssayUnreadableError` is a ValueError), or no key."""

T = TypeVar("T")
R = TypeVar("R")


async def readable(
    rows: Iterable[R], view: Callable[[R], Awaitable[T]], what: str
) -> list[T]:
    """Open each row; log one warning per row that cannot be opened and drop it."""
    out: list[T] = []
    for row in rows:
        item = await readable_one(row, view, what)
        if item is not None:
            out.append(item)
    return out


async def readable_one(
    row: R | None, view: Callable[[R], Awaitable[T]], what: str
) -> T | None:
    """Open one row, or None when it is absent or unreadable (one warning)."""
    if row is None:
        return None
    try:
        return await view(row)
    except UNREADABLE as exc:
        log.warning(
            "essay_row_unreadable",
            what=what,
            row_id=str(getattr(row, "id", "")),
            reason=type(exc).__name__,
        )
        return None

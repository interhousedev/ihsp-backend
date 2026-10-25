"""Where a user stopped in an item (LIB-6, LIB-9): last write wins by `client_ts`."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.library.domain.reader_errors import InvalidProgressError

# One report covers at most an hour of reading (the app reports every 15 seconds).
MAX_SECONDS_PER_REPORT = 3600


@dataclass(frozen=True, slots=True)
class ReadingProgress:
    """The reading position of one user in one item (books and materials only)."""

    user_id: UUID
    item_id: UUID
    file_id: UUID
    locator: dict[str, Any]
    percent: float
    opened_at: datetime
    seconds_read: int
    client_ts: datetime


def _clean_percent(percent: float) -> float:
    if math.isnan(percent) or not 0 <= percent <= 100:
        raise InvalidProgressError(params={"max": 100})
    return round(percent, 2)


def apply_progress(
    current: ReadingProgress | None,
    *,
    user_id: UUID,
    item_id: UUID,
    file_id: UUID,
    locator: Mapping[str, Any],
    percent: float,
    client_ts: datetime,
    seconds_read: int | None,
    now: datetime,
) -> ReadingProgress | None:
    """The progress after one report, or None when the report is not newer.

    A `client_ts` after the server's `now` counts as now, so a phone with a wrong
    clock cannot freeze its own position. An equal or older timestamp is a retry or
    a late offline write and is ignored entirely, reading time included.
    """
    clean = _clean_percent(percent)
    stamp = min(client_ts, now)
    if current is not None and stamp <= current.client_ts:
        return None
    seconds = max(0, min(seconds_read or 0, MAX_SECONDS_PER_REPORT))
    return ReadingProgress(
        user_id=user_id,
        item_id=item_id,
        file_id=file_id,
        locator=dict(locator),
        percent=clean,
        opened_at=stamp,
        seconds_read=(current.seconds_read if current else 0) + seconds,
        client_ts=stamp,
    )

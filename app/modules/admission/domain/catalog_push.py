"""Bulk catalog push: one result per item of a batch an agent token sends."""

from dataclasses import dataclass
from typing import Final, Literal

PushStatus = Literal["created", "updated", "unchanged", "skipped", "invalid"]
"""`skipped`: a verified country left alone; `invalid`: `field` names the problem."""

COUNTRY_BATCH_MAX: Final = 50
INSTITUTION_BATCH_MAX: Final = 25
"""Institutions mirror their logo and cover, so their batches are smaller."""
PUSH_BATCHES_PER_HOUR: Final = 200
"""Batches one account may push per hour, countries and institutions together."""


@dataclass(frozen=True, slots=True)
class PushResult:
    """What happened to one item, addressed by its index and stable key."""

    index: int
    key: str
    status: PushStatus
    field: str | None = None
    warnings: tuple[str, ...] = ()
    """Fields saved without their value, e.g. a logo that could not be fetched."""

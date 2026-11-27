"""Points ledger and leaderboard."""

from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID

__all__ = [
    "DEFAULT_POINTS",
    "LeaderRow",
    "PointEntry",
    "add_entry",
    "entry_for",
    "top",
    "total",
]

DEFAULT_POINTS: dict[str, int] = {
    "attended": 2,
    "volunteered": 5,
    "organized": 8,
    "draft_completed": 6,
    "no_show": -4,
    "position_held": 10,
    "peer_rating": 2,
}


@dataclass(frozen=True, slots=True)
class PointEntry:
    """One award; unique per (source_type, source_id, user_id, reason)."""

    user_id: UUID
    source_type: str
    source_id: UUID
    reason: str
    points: int
    at: datetime
    club_id: UUID | None = None

    @property
    def key(self) -> tuple[str, UUID, UUID, str]:
        """The dedupe identity."""
        return (self.source_type, self.source_id, self.user_id, self.reason)

    def for_club(self, club_id: UUID) -> "PointEntry":
        """The same award on a club's ledger."""
        return replace(self, club_id=club_id)


def entry_for(
    kind: str,
    user_id: UUID,
    source_id: UUID,
    at: datetime,
    settings: dict[str, int] | None = None,
) -> PointEntry:
    """Build the award for an event kind; unknown kinds raise `KeyError`."""
    values = {**DEFAULT_POINTS, **(settings or {})}
    return PointEntry(user_id, kind, source_id, kind, values[kind], at)


def add_entry(ledger: list[PointEntry], entry: PointEntry) -> bool:
    """Append unless the same source already awarded; True when added."""
    if any(e.key == entry.key for e in ledger):
        return False
    ledger.append(entry)
    return True


def total(
    ledger: list[PointEntry],
    since: datetime | None = None,
    until: datetime | None = None,
) -> int:
    """Sum of entries in [since, until)."""
    return sum(
        e.points
        for e in ledger
        if (since is None or e.at >= since) and (until is None or e.at < until)
    )


@dataclass(frozen=True, slots=True)
class LeaderRow:
    """A leaderboard line; opted-out students are masked."""

    rank: int
    user_id: UUID | None
    display_name: str
    points: int = field(default=0)


def top(
    points: dict[UUID, int],
    names: dict[UUID, str],
    opted_out: set[UUID],
    limit: int,
) -> list[LeaderRow]:
    """Competition-ranked rows (ties share a rank); zero and negative are omitted."""
    ordered = sorted(
        ((u, p) for u, p in points.items() if p > 0), key=lambda x: (-x[1], str(x[0]))
    )
    rows: list[LeaderRow] = []
    masked = 0
    rank, prev = 0, None
    for i, (user, pts) in enumerate(ordered, start=1):
        if pts != prev:
            rank, prev = i, pts
        if user in opted_out:
            masked += 1
            rows.append(LeaderRow(rank, None, f"Student #{masked}", pts))
        else:
            rows.append(LeaderRow(rank, user, names.get(user, ""), pts))
    return rows[:limit]

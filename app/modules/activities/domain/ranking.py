"""Deterministic candidate ranking for a draft round."""

from dataclasses import dataclass
from uuid import UUID

__all__ = ["Candidate", "Ranked", "Requirements", "rank_candidates"]

RECENT_CAP = 50


@dataclass(frozen=True, slots=True)
class Candidate:
    """What the ranking knows about a signup."""

    user_id: UUID
    availability: frozenset[str]
    skills: frozenset[str]
    completed: int
    no_show: int
    recent_points: int


@dataclass(frozen=True, slots=True)
class Requirements:
    """What the shift asks for."""

    availability: frozenset[str]
    skills: frozenset[str]


@dataclass(frozen=True, slots=True)
class Ranked:
    """A candidate with a score in [0, 1]."""

    user_id: UUID
    score: float


def _fit(wanted: frozenset[str], have: frozenset[str]) -> float:
    return 1.0 if not wanted else len(wanted & have) / len(wanted)


def _score(c: Candidate, req: Requirements) -> float:
    done = c.completed + c.no_show
    reliability = c.completed / done if done else 0.5
    recency = 0.5 + 0.5 * min(max(c.recent_points, 0), RECENT_CAP) / RECENT_CAP
    return (
        _fit(req.availability, c.availability)
        * _fit(req.skills, c.skills)
        * reliability
        * recency
    )


def rank_candidates(candidates: list[Candidate], req: Requirements) -> list[Ranked]:
    """Best first; ties break by user id, so the order never depends on the input."""
    scored = [Ranked(c.user_id, _score(c, req)) for c in candidates]
    return sorted(scored, key=lambda r: (-r.score, str(r.user_id)))

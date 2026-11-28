"""The overall student rating of the academic year.

Every student starts from a base score. Certificates issued in the year add points
by their category and level; a lesson-mark average above a threshold adds a bonus;
every missed lesson (platform and EMIS merged, see ``merged_absences``) and every
work-off takes points away. The score never drops below zero. Equal scores share a
place (1, 1, 3).
"""

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final
from uuid import UUID

from app.modules.academic.domain.attendance_merge import (
    AbsenceKey,
    merged_absence_count,
)
from app.modules.academic.domain.marks.group_standing import places

DEFAULT_BASE: Final = 100.0
DEFAULT_CATEGORY_POINTS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "olympiad": 10.0,
        "award": 8.0,
        "scholarship": 8.0,
        "research": 8.0,
        "academic": 6.0,
        "leadership": 5.0,
        "arts": 5.0,
        "sports": 5.0,
        "other": 3.0,
    }
)
DEFAULT_LEVEL_POINTS: Final[Mapping[str, float]] = MappingProxyType(
    {"school": 0.0, "regional": 3.0, "national": 6.0, "international": 10.0}
)
DEFAULT_MARKS_THRESHOLD: Final = 3.0
DEFAULT_MARKS_POINTS: Final = 20.0
DEFAULT_ABSENCE_POINTS: Final = 1.0
DEFAULT_WORK_OFF_POINTS: Final = 2.0

LEVEL_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "school": "school",
        "local": "regional",
        "district": "regional",
        "regional": "regional",
        "republican": "national",
        "national": "national",
        "international": "international",
    }
)
"""Level values of certificate entries mapped to the four rated levels."""


@dataclass(frozen=True, slots=True)
class RatingWeights:
    """Points of every part of the score (settings `IHSP_RATING__*` override them).

    ``category_points`` is keyed by honor category (an unknown or missing category
    counts as ``other``); ``level_points`` by rated level (an unknown level adds 0).
    ``marks_points`` is the bonus per mark point of the average above
    ``marks_threshold``.
    """

    base: float = DEFAULT_BASE
    category_points: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_CATEGORY_POINTS)
    )
    level_points: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_LEVEL_POINTS)
    )
    marks_threshold: float = DEFAULT_MARKS_THRESHOLD
    marks_points: float = DEFAULT_MARKS_POINTS
    absence_points: float = DEFAULT_ABSENCE_POINTS
    work_off_points: float = DEFAULT_WORK_OFF_POINTS


@dataclass(frozen=True, slots=True)
class RatedCertificate:
    """One certificate of the year: its name, category and raw level."""

    name: str
    category: str | None
    level: str | None
    issued_at: dt.date | None


@dataclass(frozen=True, slots=True)
class RatingInput:
    """Everything one student's score is made of in the year."""

    student_id: UUID
    group_name: str
    mark_sum: int = 0
    mark_count: int = 0
    platform_absences: Sequence[AbsenceKey] = ()
    emis_absences: Sequence[AbsenceKey] = ()
    work_offs: int = 0
    certificates: Sequence[RatedCertificate] = ()


@dataclass(frozen=True, slots=True)
class CertificatePoints:
    """A certificate with the points it brought."""

    name: str
    category: str
    level: str | None
    points: float


@dataclass(frozen=True, slots=True)
class Breakdown:
    """One student's score and each of its parts (penalties are negative)."""

    student_id: UUID
    group_name: str
    base: float
    certificates: tuple[CertificatePoints, ...]
    certificate_points: float
    mark_average: float | None
    mark_count: int
    marks_points: float
    absences: int
    absence_points: float
    work_offs: int
    work_off_points: float
    score: float


def rated_level(raw: str | None) -> str | None:
    """The rated level of a raw level value, or None when it is not one."""
    return LEVEL_ALIASES.get((raw or "").strip().lower())


def certificate_points(
    cert: RatedCertificate, weights: RatingWeights
) -> CertificatePoints:
    """Points of one certificate: its category plus its level."""
    category = cert.category or "other"
    if category not in weights.category_points:
        category = "other"
    level = rated_level(cert.level)
    points = weights.category_points.get(category, 0.0)
    if level is not None:
        points += weights.level_points.get(level, 0.0)
    return CertificatePoints(cert.name, category, level, _round(points))


def marks_bonus(average: float | None, weights: RatingWeights) -> float:
    """Bonus of a mark average: points per mark above the threshold, never negative."""
    if average is None:
        return 0.0
    return max(0.0, average - weights.marks_threshold) * weights.marks_points


def score_student(item: RatingInput, weights: RatingWeights) -> Breakdown:
    """Compute one student's breakdown."""
    certs = tuple(certificate_points(c, weights) for c in item.certificates)
    cert_total = sum(c.points for c in certs)
    average = item.mark_sum / item.mark_count if item.mark_count else None
    bonus = marks_bonus(average, weights)
    absences = merged_absence_count(item.platform_absences, item.emis_absences)
    absence_penalty = absences * weights.absence_points
    work_off_penalty = item.work_offs * weights.work_off_points
    total = weights.base + cert_total + bonus - absence_penalty - work_off_penalty
    return Breakdown(
        student_id=item.student_id,
        group_name=item.group_name,
        base=_round(weights.base),
        certificates=certs,
        certificate_points=_round(cert_total),
        mark_average=None if average is None else round(average, 2),
        mark_count=item.mark_count,
        marks_points=_round(bonus),
        absences=absences,
        absence_points=_round(-absence_penalty),
        work_offs=item.work_offs,
        work_off_points=_round(-work_off_penalty),
        score=_round(max(0.0, total)),
    )


def rank(
    items: Iterable[RatingInput], weights: RatingWeights
) -> list[tuple[int, Breakdown]]:
    """Every student's place and breakdown, best first (ties by student id)."""
    scored = {b.student_id: b for b in (score_student(i, weights) for i in items)}
    order = places((sid, b.score) for sid, b in scored.items())
    return sorted(
        ((order[sid], b) for sid, b in scored.items()),
        key=lambda pb: (pb[0], str(pb[1].student_id)),
    )


def _round(value: float) -> float:
    return round(value, 1) + 0.0

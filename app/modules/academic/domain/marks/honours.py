"""Red diploma and medal eligibility from semester marks and control marks."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.shared.contracts.honours import HonoursRules, MaxFoursRule

AwardKind = Literal["red_diploma", "gold_medal", "silver_medal"]
BlockingType = Literal["semester", "midterm", "final"]

BEST_MARK = 5
FOUR = 4


@dataclass(frozen=True, slots=True)
class SubjectSemesterMarks:
    """One subject in one semester: its rounded semester mark and control marks."""

    subject_id: UUID
    subject_name: str
    semester: int
    semester_mark: int | None
    controls: tuple[tuple[Literal["midterm", "final"], int], ...] = ()


@dataclass(frozen=True, slots=True)
class Blocking:
    """A mark that keeps a rule from passing."""

    subject_id: UUID
    subject_name: str
    semester: int
    type: BlockingType
    value: int


@dataclass(frozen=True, slots=True)
class RuleResult:
    """One enabled rule with the marks that fail it."""

    rule: str
    passed: bool
    blocking: tuple[Blocking, ...] = ()


@dataclass(frozen=True, slots=True)
class AwardResult:
    """An award: eligible when every one of its enabled rules passes."""

    kind: AwardKind
    eligible: bool
    rules: tuple[RuleResult, ...]


def serial_matches(serial: str | None, serials: Sequence[str]) -> bool:
    """Case-insensitive, trimmed comparison with the accepted serials."""
    if serial is None:
        return False
    wanted = serial.strip().casefold()
    return bool(wanted) and any(s.strip().casefold() == wanted for s in serials)


def _semester_blocking(
    rows: Sequence[SubjectSemesterMarks], keep: Callable[[int], bool]
) -> tuple[Blocking, ...]:
    return tuple(
        Blocking(r.subject_id, r.subject_name, r.semester, "semester", r.semester_mark)
        for r in rows
        if r.semester_mark is not None and keep(r.semester_mark)
    )


def _max_fours(
    name: str, rule: MaxFoursRule, rows: Sequence[SubjectSemesterMarks]
) -> RuleResult:
    """No semester mark below 4 and at most ``rule.max`` marks of 4."""
    low = _semester_blocking(rows, lambda mark: mark < FOUR)
    fours = _semester_blocking(rows, lambda mark: mark == FOUR)
    too_many = len(fours) > rule.max
    blocking = low + (fours if too_many else ())
    return RuleResult(name, not low and not too_many, blocking)


def _controls_all_five(name: str, rows: Sequence[SubjectSemesterMarks]) -> RuleResult:
    blocking = tuple(
        Blocking(r.subject_id, r.subject_name, r.semester, kind, value)
        for r in rows
        for kind, value in r.controls
        if value != BEST_MARK
    )
    return RuleResult(name, not blocking, blocking)


def _semester_all_five(name: str, rows: Sequence[SubjectSemesterMarks]) -> RuleResult:
    blocking = _semester_blocking(rows, lambda mark: mark != BEST_MARK)
    return RuleResult(name, not blocking, blocking)


def evaluate(
    rules: HonoursRules,
    rows: Sequence[SubjectSemesterMarks],
    school_certificate_serial: str | None,
) -> list[AwardResult]:
    """Evaluate every award; only enabled rules appear, an award without any is left."""
    certificate = RuleResult(
        "medal_certificate",
        serial_matches(school_certificate_serial, rules.medal_certificate.serials),
    )
    candidates: list[tuple[AwardKind, list[RuleResult | None]]] = [
        (
            "red_diploma",
            [
                (
                    _max_fours(
                        "red_diploma_max_fours", rules.red_diploma_max_fours, rows
                    )
                    if rules.red_diploma_max_fours.enabled
                    else None
                )
            ],
        ),
        (
            "gold_medal",
            [
                certificate if rules.medal_certificate.enabled else None,
                (
                    _controls_all_five("gold_controls_all_five", rows)
                    if rules.gold_controls_all_five.enabled
                    else None
                ),
                (
                    _semester_all_five("gold_semester_all_five", rows)
                    if rules.gold_semester_all_five.enabled
                    else None
                ),
            ],
        ),
        (
            "silver_medal",
            [
                certificate if rules.medal_certificate.enabled else None,
                (
                    _controls_all_five("silver_controls_all_five", rows)
                    if rules.silver_controls_all_five.enabled
                    else None
                ),
                (
                    _max_fours(
                        "silver_semester_max_fours",
                        rules.silver_semester_max_fours,
                        rows,
                    )
                    if rules.silver_semester_max_fours.enabled
                    else None
                ),
            ],
        ),
    ]
    awards: list[AwardResult] = []
    for kind, parts in candidates:
        enabled = tuple(part for part in parts if part is not None)
        if enabled:
            awards.append(AwardResult(kind, all(r.passed for r in enabled), enabled))
    return awards

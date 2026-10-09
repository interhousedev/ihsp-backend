"""Mark planner: the predicted semester mark and what the controls must bring.

Built on the ACA-15 formula in `grading.semester_mark`: the mean of the lesson,
midterm and final means that have marks. Every number here comes from calling that
formula, so the planner can never disagree with the mark a student sees.

A semester has `MIDTERMS_PER_SEMESTER` midterm controls and one final control, each
giving one whole mark from 2 to 5. The controls that have no mark yet are the
*remaining* ones; the planner puts the same mark on every remaining control of a
type ("a 4 on each remaining midterm"), which keeps the answer readable.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.modules.academic.domain.marks import grading
from app.modules.academic.domain.marks.errors import InvalidWhatIfError

MarkType = Literal["lesson", "midterm", "final"]
Control = Literal["midterm", "final"]
TargetStatus = Literal["secured", "needed", "not_reachable", "unknown"]
Assumption = Literal[
    "rounding",
    "controls_per_semester",
    "same_mark_on_remaining",
    "pending_as_lesson_average",
    "no_lesson_marks",
    "what_if",
]

MIN_MARK = 2
MAX_MARK = 5
MAX_WHAT_IF = 20
MIDTERMS_PER_SEMESTER = 2
FINALS_PER_SEMESTER = 1
TARGET_GRADES: tuple[int, ...] = (5, 4, 3)
_MARKS = range(MIN_MARK, MAX_MARK + 1)
_MARK_TYPES: dict[str, MarkType] = {
    "lesson": "lesson",
    "midterm": "midterm",
    "final": "final",
}
_HALF = Decimal("0.5")
_WHOLE = Decimal(1)


def threshold(grade: int) -> Decimal:
    """Return the lowest semester mark that rounds to the grade (4.50 for a 5)."""
    return Decimal(grade) - _HALF


def grade_of(mark: Decimal) -> int:
    """Return the whole grade a semester mark rounds to (halves go up)."""
    return int(mark.quantize(_WHOLE, rounding=ROUND_HALF_UP))


def assumed_mark(lesson_average: Decimal | None) -> int | None:
    """Return the mark a remaining control is assumed to get: the lesson average, whole.

    None when there are no lesson marks to base the assumption on.
    """
    if lesson_average is None:
        return None
    return min(MAX_MARK, max(MIN_MARK, grade_of(lesson_average)))


@dataclass(frozen=True, slots=True)
class MarkStat:
    """How many marks of one type there are and their average."""

    count: int
    average: Decimal | None


@dataclass(frozen=True, slots=True)
class Remaining:
    """How many midterm and final controls of the semester have no mark yet."""

    midterm: int
    final: int


@dataclass(frozen=True, slots=True)
class FinalForMidterm:
    """The lowest final that works when each remaining midterm gets ``midterm``."""

    midterm: int
    min_final: int | None


@dataclass(frozen=True, slots=True)
class TargetPlan:
    """What it takes to end the semester with one grade.

    ``secured``: reached whatever the remaining controls bring. ``not_reachable``:
    even the best marks fall short. ``unknown``: no lesson marks yet, so there is no
    base to plan from. ``needed``: with one kind of control remaining ``control`` and
    ``min_value`` say what each remaining one must reach; with both kinds remaining
    ``min_both`` is the lowest mark that works on all of them and ``pairs`` lists the
    lowest final for each midterm mark.
    """

    grade: int
    threshold: Decimal
    status: TargetStatus
    control: Control | None = None
    min_value: int | None = None
    min_both: int | None = None
    pairs: tuple[FinalForMidterm, ...] = ()


@dataclass(frozen=True, slots=True)
class Prediction:
    """The semester mark if remaining controls get the assumed marks."""

    value: Decimal | None
    midterm: int | None
    final: int | None


@dataclass(frozen=True, slots=True)
class Plan:
    """The whole planner answer for one subject and semester."""

    lesson: MarkStat
    midterm: MarkStat
    final: MarkStat
    semester_mark: Decimal | None
    components: tuple[MarkType, ...]
    missing: tuple[MarkType, ...]
    remaining: Remaining
    pending: tuple[Control, ...]
    predicted: Prediction
    targets: tuple[TargetPlan, ...]
    assumptions: tuple[Assumption, ...]


def _stat(values: Sequence[int]) -> MarkStat:
    return MarkStat(count=len(values), average=grading.average(values))


def _remaining(midterm: Sequence[int], final: Sequence[int]) -> Remaining:
    return Remaining(
        midterm=max(0, MIDTERMS_PER_SEMESTER - len(midterm)),
        final=max(0, FINALS_PER_SEMESTER - len(final)),
    )


def _pending(remaining: Remaining) -> tuple[Control, ...]:
    pending: list[Control] = []
    if remaining.midterm:
        pending.append("midterm")
    if remaining.final:
        pending.append("final")
    return tuple(pending)


def _reaches(mark: Decimal | None, limit: Decimal) -> bool:
    return mark is not None and mark >= limit


@dataclass(frozen=True, slots=True)
class _Marks:
    """The real marks and how many controls are still to come."""

    lesson: Sequence[int]
    midterm: Sequence[int]
    final: Sequence[int]
    remaining: Remaining

    def mark(self, midterm: int | None, final: int | None) -> Decimal | None:
        """Return the semester mark with a mark on every remaining control.

        Each remaining midterm gets ``midterm`` and each remaining final ``final``;
        None leaves that kind of control without a mark.
        """
        return grading.semester_mark(
            self.lesson,
            self._fill(self.midterm, self.remaining.midterm, midterm),
            self._fill(self.final, self.remaining.final, final),
        )

    @staticmethod
    def _fill(real: Sequence[int], count: int, value: int | None) -> list[int]:
        return [*real] if value is None else [*real, *([value] * count)]


def _lowest(marks: _Marks, control: Control, limit: Decimal) -> int | None:
    """Return the lowest mark on each remaining ``control`` that reaches ``limit``."""
    for value in _MARKS:
        got = (
            marks.mark(value, None) if control == "midterm" else marks.mark(None, value)
        )
        if _reaches(got, limit):
            return value
    return None


def _one_pending(
    grade: int, limit: Decimal, marks: _Marks, control: Control
) -> TargetPlan:
    lowest = _lowest(marks, control, limit)
    if lowest is None:
        return TargetPlan(grade, limit, "not_reachable")
    if lowest == MIN_MARK:
        return TargetPlan(grade, limit, "secured")
    return TargetPlan(grade, limit, "needed", control=control, min_value=lowest)


def _both_pending(grade: int, limit: Decimal, marks: _Marks) -> TargetPlan:
    def reaches(midterm: int, final: int) -> bool:
        return _reaches(marks.mark(midterm, final), limit)

    if reaches(MIN_MARK, MIN_MARK):
        return TargetPlan(grade, limit, "secured")
    if not reaches(MAX_MARK, MAX_MARK):
        return TargetPlan(grade, limit, "not_reachable")
    min_both = next(v for v in _MARKS if reaches(v, v))
    pairs = tuple(
        FinalForMidterm(m, next((f for f in _MARKS if reaches(m, f)), None))
        for m in reversed(_MARKS)
    )
    return TargetPlan(grade, limit, "needed", min_both=min_both, pairs=pairs)


def _target(grade: int, marks: _Marks, pending: tuple[Control, ...]) -> TargetPlan:
    limit = threshold(grade)
    if not marks.lesson:
        return TargetPlan(grade, limit, "unknown")
    if not pending:
        reached = _reaches(marks.mark(None, None), limit)
        return TargetPlan(grade, limit, "secured" if reached else "not_reachable")
    if len(pending) == 1:
        return _one_pending(grade, limit, marks, pending[0])
    return _both_pending(grade, limit, marks)


def _predict(marks: _Marks, lesson_average: Decimal | None) -> Prediction:
    guess = assumed_mark(lesson_average)
    if guess is None:
        return Prediction(None, None, None)
    remaining = marks.remaining
    return Prediction(
        value=marks.mark(guess, guess),
        midterm=guess if remaining.midterm else None,
        final=guess if remaining.final else None,
    )


def _assumptions(
    remaining: Remaining, has_lesson: bool, what_if: int
) -> tuple[Assumption, ...]:
    found: list[Assumption] = ["rounding"]
    if remaining.midterm or remaining.final:
        found.append("controls_per_semester")
    if remaining.midterm > 1:
        found.append("same_mark_on_remaining")
    if (remaining.midterm or remaining.final) and has_lesson:
        found.append("pending_as_lesson_average")
    if not has_lesson:
        found.append("no_lesson_marks")
    if what_if:
        found.append("what_if")
    return tuple(found)


def plan(
    lesson: Sequence[int],
    midterm: Sequence[int],
    final: Sequence[int],
    *,
    what_if_count: int = 0,
) -> Plan:
    """Build the planner answer from the marks of one subject and semester.

    ``what_if_count`` only says that hypothetical marks are already inside the
    lists, so the answer names that in its assumptions.
    """
    stats = (_stat(lesson), _stat(midterm), _stat(final))
    remaining = _remaining(midterm, final)
    pending = _pending(remaining)
    marks = _Marks(lesson, midterm, final, remaining)
    types: tuple[MarkType, ...] = ("lesson", "midterm", "final")
    present = tuple(t for t, stat in zip(types, stats, strict=True) if stat.count > 0)
    return Plan(
        lesson=stats[0],
        midterm=stats[1],
        final=stats[2],
        semester_mark=grading.semester_mark(lesson, midterm, final),
        components=present,
        missing=tuple(t for t in types if t not in present),
        remaining=remaining,
        pending=pending,
        predicted=_predict(marks, stats[0].average),
        targets=tuple(_target(grade, marks, pending) for grade in TARGET_GRADES),
        assumptions=_assumptions(remaining, bool(lesson), what_if_count),
    )


@dataclass(frozen=True, slots=True)
class HypotheticalMark:
    """A mark the student wants to try: ``midterm:4`` is "what if I get a 4"."""

    type: MarkType
    value: int


def parse_what_if(raw: str) -> HypotheticalMark:
    """Parse ``<type>:<value>``; raises InvalidWhatIfError on anything else."""
    kind, _, text = raw.partition(":")
    mark_type = _MARK_TYPES.get(kind)
    if mark_type is None or not (text.isascii() and text.isdigit()):
        raise InvalidWhatIfError(params={"value": raw[:40]})
    value = int(text)
    if not MIN_MARK <= value <= MAX_MARK:
        raise InvalidWhatIfError(params={"value": raw[:40]})
    return HypotheticalMark(type=mark_type, value=value)


def add_hypothetical(
    lesson: Sequence[int],
    midterm: Sequence[int],
    final: Sequence[int],
    extra: Sequence[HypotheticalMark],
) -> tuple[list[int], list[int], list[int]]:
    """Return the three mark lists with the hypothetical marks appended."""
    if len(extra) > MAX_WHAT_IF:
        raise InvalidWhatIfError(params={"max": MAX_WHAT_IF})
    lists: dict[str, list[int]] = {
        "lesson": list(lesson),
        "midterm": list(midterm),
        "final": list(final),
    }
    for mark in extra:
        lists[mark.type].append(mark.value)
    return lists["lesson"], lists["midterm"], lists["final"]

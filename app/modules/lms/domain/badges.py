"""Course badges: the design, the rule AST, its validation and its evaluation.

A badge rule is a small tree built in the visual editor:

    {"event": "<event>", "condition": <condition> | null}

and a condition is one of

    {"op": "score_gte", "value": 0..100}      the event score in percent
    {"op": "count_gte", "value": 1..1000}     the running count of the event
    {"op": "section_is", "section_id": "..."} the event happened in this section
    {"op": "step_is", "step_id": "<uuid>"}    the event happened in this step
    {"op": "within_days_of_enroll", "value": 1..365}  at most N days after enrolling
    {"op": "and" | "or", "children": [...]}   2..8 children
    {"op": "not", "child": {...}}

The tree is plain data. It is parsed into frozen dataclasses with bounded depth
and size and evaluated by a pattern match; nothing is ever executed.
"""

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.modules.lms.domain.engagement.streak import compute_streak
from app.shared.base_error import ValidationFailedError

MAX_DEPTH = 6
MAX_NODES = 32
MAX_ITEMS = 8
MAX_BADGES_PER_COURSE = 50
NAME_MAX = 60
DESCRIPTION_MAX = 300
LOCALES = ("uz", "ru", "en")
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
IMAGE_MAX_BYTES = 512 * 1024
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_SECTION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class BadgeInvalidError(ValidationFailedError):
    """A badge design or rule is malformed (`params.field`, `params.reason`)."""

    code = "lms/badge-invalid"
    message_key = "lms-badge-invalid"


def bad(field: str, reason: str) -> BadgeInvalidError:
    """Return the validation error of one field."""
    return BadgeInvalidError(params={"field": field, "reason": reason})


class BadgeIcon(StrEnum):
    """The built-in icon set."""

    STAR = "star"
    TROPHY = "trophy"
    MEDAL = "medal"
    FLAME = "flame"
    BOOK = "book"
    ROCKET = "rocket"
    BOLT = "bolt"
    HEART = "heart"
    CROWN = "crown"
    TARGET = "target"
    BRAIN = "brain"
    CHECK = "check"


class BadgeShape(StrEnum):
    """The frame drawn around the icon."""

    CIRCLE = "circle"
    SHIELD = "shield"
    HEXAGON = "hexagon"
    STAR = "star"


class BadgeEvent(StrEnum):
    """The WHEN block: what happened to the learner."""

    STEP_COMPLETED = "step_completed"
    SECTION_COMPLETED = "section_completed"
    TEST_PASSED = "test_passed"
    EXAM_SCORED = "exam_scored"
    STREAK_REACHED = "streak_reached"
    COURSE_COMPLETED = "course_completed"
    REVIEWS_DONE = "reviews_done"
    # Platform events: facts across all of the learner's courses.
    LEVEL_REACHED = "level_reached"
    COACH_RESOLVED = "coach_resolved"
    COURSES_COMPLETED = "courses_completed"


AGGREGATE_EVENTS = frozenset(
    {
        BadgeEvent.LEVEL_REACHED,
        BadgeEvent.COACH_RESOLVED,
        BadgeEvent.COURSES_COMPLETED,
    }
)


# - - - Rule AST - - -


@dataclass(frozen=True, slots=True)
class ScoreAtLeast:
    """The event score in percent is at least ``value``."""

    value: int


@dataclass(frozen=True, slots=True)
class CountAtLeast:
    """The running count (nth step, section, test), streak or reviews a day."""

    value: int


@dataclass(frozen=True, slots=True)
class SectionIs:
    """The event happened in this section."""

    section_id: str


@dataclass(frozen=True, slots=True)
class StepIs:
    """The event happened in this step."""

    step_id: UUID


@dataclass(frozen=True, slots=True)
class WithinDays:
    """The event happened at most ``value`` days after enrolling."""

    value: int


@dataclass(frozen=True, slots=True)
class AllOf:
    """Every child holds."""

    items: tuple["Condition", ...]


@dataclass(frozen=True, slots=True)
class AnyOf:
    """At least one child holds."""

    items: tuple["Condition", ...]


@dataclass(frozen=True, slots=True)
class Not:
    """The child does not hold."""

    item: "Condition"


Condition = (
    ScoreAtLeast | CountAtLeast | SectionIs | StepIs | WithinDays | AllOf | AnyOf | Not
)


@dataclass(frozen=True, slots=True)
class BadgeRule:
    """WHEN ``event`` IF ``condition`` THEN award the badge."""

    event: BadgeEvent
    condition: Condition | None


_BOUNDS = {
    "score_gte": (0, 100),
    "count_gte": (1, 1000),
    "within_days_of_enroll": (1, 365),
}


def _number(raw: Mapping[str, Any], op: str) -> int:
    low, high = _BOUNDS[op]
    value = raw.get("value")
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("rule", "number-expected")
    if not low <= value <= high:
        raise bad("rule", "number-out-of-range")
    return value


def _section(raw: Mapping[str, Any]) -> SectionIs:
    section_id = raw.get("section_id")
    if not isinstance(section_id, str) or not _SECTION_ID.match(section_id):
        raise bad("rule", "section-expected")
    return SectionIs(section_id)


def _step(raw: Mapping[str, Any]) -> StepIs:
    try:
        return StepIs(UUID(str(raw.get("step_id"))))
    except ValueError:
        raise bad("rule", "step-expected") from None


_LEAVES: dict[str, Callable[[Mapping[str, Any]], Condition]] = {
    "score_gte": lambda raw: ScoreAtLeast(_number(raw, "score_gte")),
    "count_gte": lambda raw: CountAtLeast(_number(raw, "count_gte")),
    "within_days_of_enroll": lambda raw: WithinDays(
        _number(raw, "within_days_of_enroll")
    ),
    "section_is": _section,
    "step_is": _step,
}


class _Parser:
    """Turns the stored JSON into the AST, counting nodes and depth."""

    def __init__(self) -> None:
        self.nodes = 0

    def condition(self, raw: Any, depth: int) -> Condition:  # noqa: ANN401 - JSON
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise bad("rule", "too-many-blocks")
        if depth > MAX_DEPTH:
            raise bad("rule", "too-deep")
        if not isinstance(raw, Mapping):
            raise bad("rule", "not-an-object")
        op = raw.get("op")
        leaf = _LEAVES.get(op) if isinstance(op, str) else None
        if leaf is not None:
            return leaf(raw)
        if op in ("and", "or"):
            return self._group(op, raw.get("children"), depth)
        if op == "not":
            return Not(self.condition(raw.get("child"), depth + 1))
        raise bad("rule", "unknown-block")

    def _group(self, op: str, items: Any, depth: int) -> Condition:  # noqa: ANN401
        if not isinstance(items, list) or not 2 <= len(items) <= MAX_ITEMS:
            raise bad("rule", "children-count")
        children = tuple(self.condition(item, depth + 1) for item in items)
        return AllOf(children) if op == "and" else AnyOf(children)


def parse_rule(raw: Any) -> BadgeRule:  # noqa: ANN401 - stored or posted JSON
    """Validate the rule JSON and return its AST; raise BadgeInvalidError."""
    if not isinstance(raw, Mapping):
        raise bad("rule", "not-an-object")
    try:
        event = BadgeEvent(str(raw.get("event")))
    except ValueError:
        raise bad("rule", "unknown-event") from None
    condition_raw = raw.get("condition")
    condition = None if condition_raw is None else _Parser().condition(condition_raw, 1)
    return BadgeRule(event, condition)


def dump_condition(node: Condition) -> dict[str, Any]:
    """Return the canonical JSON of a condition."""
    match node:
        case ScoreAtLeast(value):
            return {"op": "score_gte", "value": value}
        case CountAtLeast(value):
            return {"op": "count_gte", "value": value}
        case WithinDays(value):
            return {"op": "within_days_of_enroll", "value": value}
        case SectionIs(section_id):
            return {"op": "section_is", "section_id": section_id}
        case StepIs(step_id):
            return {"op": "step_is", "step_id": str(step_id)}
        case AllOf(items):
            return {"op": "and", "children": [dump_condition(i) for i in items]}
        case AnyOf(items):
            return {"op": "or", "children": [dump_condition(i) for i in items]}
        case Not(item):
            return {"op": "not", "child": dump_condition(item)}


def dump_rule(rule: BadgeRule) -> dict[str, Any]:
    """Return the canonical JSON of a rule (what is stored)."""
    return {
        "event": rule.event.value,
        "condition": None if rule.condition is None else dump_condition(rule.condition),
    }


def referenced_steps(node: Condition | None) -> set[UUID]:
    """Return the step ids a condition names."""
    match node:
        case StepIs(step_id):
            return {step_id}
        case AllOf(items) | AnyOf(items):
            return set().union(*(referenced_steps(i) for i in items))
        case Not(item):
            return referenced_steps(item)
    return set()


def referenced_sections(node: Condition | None) -> set[str]:
    """Return the section ids a condition names."""
    match node:
        case SectionIs(section_id):
            return {section_id}
        case AllOf(items) | AnyOf(items):
            return set().union(*(referenced_sections(i) for i in items))
        case Not(item):
            return referenced_sections(item)
    return set()


# - - - Design - - -


@dataclass(frozen=True, slots=True)
class BadgeDesign:
    """What a badge looks like: names, description and an icon or an image."""

    name: dict[str, str]
    description: dict[str, str]
    icon: BadgeIcon
    color: str
    shape: BadgeShape
    image_file_id: UUID | None


def clean_texts(
    field: str, raw: Mapping[str, str], limit: int, *, required: bool
) -> dict[str, str]:
    """Trim the uz/ru/en texts; a required text needs at least one locale."""
    unknown = set(raw) - set(LOCALES)
    if unknown:
        raise bad(field, "unknown-locale")
    texts = {k: " ".join(str(raw.get(k, "")).split()) for k in LOCALES}
    if any(len(v) > limit for v in texts.values()):
        raise bad(field, "too-long")
    if required and not any(texts.values()):
        raise bad(field, "required")
    return texts


def clean_color(value: str) -> str:
    """Return a lower case `#rrggbb` colour."""
    if not _COLOR.match(value):
        raise bad("color", "hex")
    return value.lower()


def check_image(content_type: str, byte_size: int) -> None:
    """Raise unless the uploaded image is a small PNG, JPEG or WebP."""
    if content_type not in IMAGE_TYPES:
        raise bad("image_file_id", "image-type")
    if byte_size > IMAGE_MAX_BYTES:
        raise bad("image_file_id", "image-too-large")


# - - - Evaluation - - -


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One happening of an event with the facts the conditions read."""

    kind: BadgeEvent
    at: datetime
    step_id: UUID | None = None
    section_id: str | None = None
    score: float | None = None
    count: int | None = None


def holds(node: Condition | None, event: Occurrence, enrolled_at: datetime) -> bool:
    """Return True when the condition holds for this occurrence."""
    match node:
        case None:
            return True
        case ScoreAtLeast(value):
            return event.score is not None and event.score >= value
        case CountAtLeast(value):
            return event.count is not None and event.count >= value
        case SectionIs(section_id):
            return event.section_id == section_id
        case StepIs(step_id):
            return event.step_id == step_id
        case WithinDays(value):
            return event.at - enrolled_at <= timedelta(days=value)
        case AllOf(items):
            return all(holds(i, event, enrolled_at) for i in items)
        case AnyOf(items):
            return any(holds(i, event, enrolled_at) for i in items)
        case Not(item):
            return not holds(item, event, enrolled_at)
    return False


def first_match(
    rule: BadgeRule, events: Iterable[Occurrence], enrolled_at: datetime
) -> Occurrence | None:
    """Return the first occurrence (by time) that satisfies the rule."""
    matching = [
        e
        for e in events
        if e.kind is rule.event and holds(rule.condition, e, enrolled_at)
    ]
    return min(matching, key=lambda e: e.at) if matching else None


@dataclass(frozen=True, slots=True)
class LearnerFacts:
    """Everything the evaluator needs about one learner in one course."""

    enrolled_at: datetime
    course_completed_at: datetime | None
    sections: Sequence[tuple[str, Sequence[UUID]]]
    completed_steps: Mapping[UUID, datetime]
    step_scores: Mapping[UUID, float]
    passed_tests: Sequence[tuple[UUID, datetime, float]]
    exam_scores: Sequence[tuple[UUID, datetime, float]]
    active_days: Sequence[date]
    today: date
    reviews_per_day: Mapping[date, int]


def _day_end(day: date, tz_of: datetime) -> datetime:
    return datetime.combine(day, datetime.max.time(), tzinfo=tz_of.tzinfo)


def _step_events(
    facts: LearnerFacts, section_of: Mapping[UUID, str]
) -> Iterable[Occurrence]:
    ordered = sorted(facts.completed_steps.items(), key=lambda item: item[1])
    for n, (step_id, at) in enumerate(ordered, start=1):
        yield Occurrence(
            BadgeEvent.STEP_COMPLETED,
            at,
            step_id,
            section_of.get(step_id),
            facts.step_scores.get(step_id),
            count=n,
        )


def _section_events(facts: LearnerFacts) -> Iterable[Occurrence]:
    done = []
    for section_id, step_ids in facts.sections:
        if not step_ids or any(s not in facts.completed_steps for s in step_ids):
            continue
        at = max(facts.completed_steps[s] for s in step_ids)
        scores = [facts.step_scores[s] for s in step_ids if s in facts.step_scores]
        mean = sum(scores) / len(scores) if scores else None
        done.append((at, section_id, mean))
    done.sort(key=lambda item: item[0])
    for n, (at, section_id, mean) in enumerate(done, start=1):
        yield Occurrence(
            BadgeEvent.SECTION_COMPLETED, at, None, section_id, mean, count=n
        )


def _scored_events(
    facts: LearnerFacts, section_of: Mapping[UUID, str]
) -> Iterable[Occurrence]:
    for kind, rows in (
        (BadgeEvent.TEST_PASSED, facts.passed_tests),
        (BadgeEvent.EXAM_SCORED, facts.exam_scores),
    ):
        ordered = sorted(rows, key=lambda row: row[1])
        for n, (step_id, at, score) in enumerate(ordered, start=1):
            yield Occurrence(kind, at, step_id, section_of.get(step_id), score, count=n)


def _habit_events(facts: LearnerFacts) -> Iterable[Occurrence]:
    if facts.course_completed_at is not None:
        yield Occurrence(BadgeEvent.COURSE_COMPLETED, facts.course_completed_at)
    if facts.active_days:
        streak = compute_streak(facts.active_days, facts.today).best
        at = _day_end(max(facts.active_days), facts.enrolled_at)
        yield Occurrence(BadgeEvent.STREAK_REACHED, at, count=streak)
    for day, count in facts.reviews_per_day.items():
        at = _day_end(day, facts.enrolled_at)
        yield Occurrence(BadgeEvent.REVIEWS_DONE, at, count=count)


def occurrences(facts: LearnerFacts) -> list[Occurrence]:
    """Derive every event occurrence from the stored facts (replayable)."""
    section_of = {
        step_id: section_id
        for section_id, step_ids in facts.sections
        for step_id in step_ids
    }
    return [
        *_step_events(facts, section_of),
        *_section_events(facts),
        *_scored_events(facts, section_of),
        *_habit_events(facts),
    ]


def earned(
    rules: Mapping[UUID, BadgeRule], facts: LearnerFacts
) -> dict[UUID, datetime]:
    """Return the badges whose rule is met, with the time it was first met."""
    events = occurrences(facts)
    result: dict[UUID, datetime] = {}
    for badge_id, rule in rules.items():
        match = first_match(rule, events, facts.enrolled_at)
        if match is not None:
            result[badge_id] = match.at
    return result

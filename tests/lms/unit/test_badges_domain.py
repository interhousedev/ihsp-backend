"""Badge rules: bounded parsing of hostile trees and the evaluator."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.modules.lms.domain.badges import (
    BadgeInvalidError,
    LearnerFacts,
    dump_rule,
    earned,
    parse_rule,
)

import pytest

T0 = datetime(2026, 9, 7, 9, tzinfo=UTC)


def _deep(levels: int) -> dict[str, Any]:
    node: dict[str, Any] = {"op": "score_gte", "value": 50}
    for _ in range(levels):
        node = {"op": "not", "child": node}
    return node


@pytest.mark.parametrize(
    "raw",
    [
        {"event": "rm -rf", "condition": None},
        {"event": "test_passed", "condition": {"op": "__import__"}},
        {"event": "test_passed", "condition": _deep(20)},
        {"event": "test_passed", "condition": {"op": "and", "children": []}},
        {"event": "test_passed", "condition": {"op": "score_gte", "value": "1e999"}},
        {
            "event": "test_passed",
            "condition": {
                "op": "or",
                "children": [
                    {"op": "and", "children": [_deep(1)] * 8} for _ in range(8)
                ],
            },
        },
        "not a dict",
    ],
)
def test_malicious_rules_are_rejected(raw: Any) -> None:
    with pytest.raises(BadgeInvalidError):
        parse_rule(raw)


def test_rule_round_trips() -> None:
    raw = {
        "event": "test_passed",
        "condition": {
            "op": "and",
            "children": [
                {"op": "score_gte", "value": 90},
                {"op": "within_days_of_enroll", "value": 7},
            ],
        },
    }
    assert dump_rule(parse_rule(raw)) == raw


def test_evaluator_awards_only_met_rules() -> None:
    step = uuid4()
    facts = LearnerFacts(
        enrolled_at=T0,
        course_completed_at=None,
        sections=[("s1", [step])],
        completed_steps={step: T0 + timedelta(hours=1)},
        step_scores={step: 95.0},
        passed_tests=[(step, T0 + timedelta(hours=1), 95.0)],
        exam_scores=[],
        active_days=[date(2026, 9, 7)],
        today=date(2026, 9, 7),
        reviews_per_day={},
    )
    first, high, done = uuid4(), uuid4(), uuid4()
    rules = {
        first: parse_rule({"event": "step_completed", "condition": None}),
        high: parse_rule(
            {"event": "test_passed", "condition": {"op": "score_gte", "value": 99}}
        ),
        done: parse_rule({"event": "course_completed", "condition": None}),
    }
    assert set(earned(rules, facts)) == {first}


def test_count_rule_counts_progress_already_made() -> None:
    """A new "N steps completed" badge counts earlier steps (retroactive)."""
    a, b, c = uuid4(), uuid4(), uuid4()
    facts = LearnerFacts(
        enrolled_at=T0,
        course_completed_at=None,
        sections=[("s1", [a, b]), ("s2", [c])],
        completed_steps={b: T0 + timedelta(hours=2), a: T0 + timedelta(hours=1)},
        step_scores={},
        passed_tests=[],
        exam_scores=[],
        active_days=[],
        today=date(2026, 9, 7),
        reviews_per_day={},
    )

    def rule(event: str, n: int) -> Any:  # noqa: ANN401 - parsed rule
        return parse_rule(
            {"event": event, "condition": {"op": "count_gte", "value": n}}
        )

    one, two, three, section = uuid4(), uuid4(), uuid4(), uuid4()
    rules = {
        one: rule("step_completed", 1),
        two: rule("step_completed", 2),
        three: rule("step_completed", 3),
        section: rule("section_completed", 1),
    }
    got = earned(rules, facts)
    assert set(got) == {one, two, section}
    assert got[one] == T0 + timedelta(hours=1)
    assert got[two] == T0 + timedelta(hours=2)

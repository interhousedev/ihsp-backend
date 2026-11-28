"""Badge v2 domain: scope invariants, platform events, templates (spec 2.6).

The implementation must provide:
  app.modules.lms.domain.badges (extended):
    BadgeEvent.LEVEL_REACHED 'level_reached', COACH_RESOLVED 'coach_resolved',
    COURSES_COMPLETED 'courses_completed'  (parse_rule accepts them)
    AGGREGATE_EVENTS: frozenset of those three
  app.modules.lms.domain.badge_model:
    BadgeScope ('course'|'platform')
    Badge(id, scope, course_id, name, description, image, rule, template_code,
          template_params, enabled, version).validate() raises
          BadgeInvalidError(params.field)
    Badge.with_rule(rule, *, at) -> new Badge with version + 1
  app.modules.lms.domain.badge_templates:
    TEMPLATE_CODES == ('first_lesson','section_master','streak_7','fast_finisher',
                       'comeback','coach_scholar')
    list_templates() -> [BadgeTemplate(code, params: [ParamSpec(name, min, max,
    default)], scope)]
    compile_template(code, params) -> rule dict (always parse_rule-valid);
      raises BadgeInvalidError for unknown code / missing / out-of-range params
Platform badges accept ONLY AGGREGATE_EVENTS (validate raises otherwise).
Boring choices: first_lesson=step_completed; section_master(section_id, pct 50..100)
= section_completed + score_gte; streak_7=streak_reached count 7; fast_finisher(days
1..365)=course_completed within_days_of_enroll; comeback = reviews_done count_gte
(param count); coach_scholar = coach_resolved count_gte (platform only).
"""

from uuid import uuid4

from app.modules.lms.domain.badge_model import Badge, BadgeScope
from app.modules.lms.domain.badge_templates import (
    TEMPLATE_CODES,
    compile_template,
    list_templates,
)
from app.modules.lms.domain.badges import (
    AGGREGATE_EVENTS,
    BadgeEvent,
    BadgeInvalidError,
    dump_rule,
    parse_rule,
)

import pytest

NAME = {"uz": "a", "ru": "b", "en": "c"}
RULE = {"event": "step_completed", "condition": None}


def badge(**kw: object) -> Badge:
    base: dict[str, object] = {
        "id": uuid4(),
        "scope": BadgeScope.COURSE,
        "course_id": uuid4(),
        "name": NAME,
        "description": {"en": "d"},
        "image": None,
        "rule": RULE,
        "template_code": None,
        "template_params": None,
        "enabled": True,
        "version": 1,
    }
    base.update(kw)
    return Badge(**base)  # type: ignore[arg-type]


def test_course_badge_needs_a_course() -> None:
    badge().validate()
    with pytest.raises(BadgeInvalidError):
        badge(course_id=None).validate()


PLATFORM_RULE = {"event": "level_reached", "condition": {"op": "count_gte", "value": 3}}


def test_platform_badge_must_not_have_a_course() -> None:
    badge(scope=BadgeScope.PLATFORM, course_id=None, rule=PLATFORM_RULE).validate()
    with pytest.raises(BadgeInvalidError):
        badge(
            scope=BadgeScope.PLATFORM, course_id=uuid4(), rule=PLATFORM_RULE
        ).validate()


@pytest.mark.parametrize(
    "event",
    ["step_completed", "section_completed", "course_completed", "streak_reached"],
)
def test_platform_badges_accept_only_the_aggregate_events(event: str) -> None:
    """Spec 2.6.9: a platform rule has no course facts to evaluate a per-course
    event."""
    with pytest.raises(BadgeInvalidError):
        badge(
            scope=BadgeScope.PLATFORM,
            course_id=None,
            rule={"event": event, "condition": None},
        ).validate()


def test_rule_must_parse() -> None:
    with pytest.raises(BadgeInvalidError):
        badge(rule={"event": "nope", "condition": None}).validate()


def test_platform_rule_may_not_reference_course_steps_or_sections() -> None:
    step = {
        "event": "step_completed",
        "condition": {"op": "step_is", "step_id": str(uuid4())},
    }
    sec = {
        "event": "section_completed",
        "condition": {"op": "section_is", "section_id": "s1"},
    }
    for rule in (step, sec):
        with pytest.raises(BadgeInvalidError):
            badge(scope=BadgeScope.PLATFORM, course_id=None, rule=rule).validate()


@pytest.mark.parametrize(
    "event", ["level_reached", "coach_resolved", "courses_completed"]
)
def test_aggregate_events_parse_and_are_platform_only(event: str) -> None:
    rule = {"event": event, "condition": {"op": "count_gte", "value": 3}}
    assert dump_rule(parse_rule(rule)) == rule
    badge(scope=BadgeScope.PLATFORM, course_id=None, rule=rule).validate()
    with pytest.raises(BadgeInvalidError):
        badge(rule=rule).validate()


def test_aggregate_events_constant() -> None:
    assert AGGREGATE_EVENTS == {
        BadgeEvent.LEVEL_REACHED,
        BadgeEvent.COACH_RESOLVED,
        BadgeEvent.COURSES_COMPLETED,
    }


def test_rule_change_bumps_the_version() -> None:
    from datetime import UTC, datetime

    b = badge()
    new = b.with_rule(
        {"event": "course_completed", "condition": None}, at=datetime.now(UTC)
    )
    assert new.version == b.version + 1 and b.version == 1


def test_template_catalogue() -> None:
    assert tuple(t.code for t in list_templates()) == TEMPLATE_CODES
    assert all(len(t.params) <= 2 for t in list_templates())


@pytest.mark.parametrize(
    ("code", "params"),
    [
        ("first_lesson", {}),
        ("section_master", {"section_id": "sec-1", "pct": 90}),
        ("streak_7", {}),
        ("fast_finisher", {"days": 14}),
        ("comeback", {"count": 5}),
    ],
)
def test_course_templates_compile_to_valid_rules(
    code: str, params: dict[str, object]
) -> None:
    parse_rule(compile_template(code, params))


def test_coach_scholar_is_a_platform_template() -> None:
    rule = compile_template("coach_scholar", {"count": 5})
    assert rule["event"] == "coach_resolved"
    parse_rule(rule)


def test_template_parameters_are_range_checked() -> None:
    with pytest.raises(BadgeInvalidError):
        compile_template("section_master", {"section_id": "s", "pct": 20})
    with pytest.raises(BadgeInvalidError):
        compile_template("fast_finisher", {"days": 0})
    with pytest.raises(BadgeInvalidError):
        compile_template("section_master", {"pct": 90})  # missing section_id
    with pytest.raises(BadgeInvalidError):
        compile_template("no_such", {})


def test_section_master_rule_shape() -> None:
    rule = compile_template("section_master", {"section_id": "sec-1", "pct": 90})
    assert rule["event"] == "section_completed"
    ops = {c["op"] for c in rule["condition"]["children"]}
    assert ops == {"section_is", "score_gte"}

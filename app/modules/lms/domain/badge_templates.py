"""Ready-made badge rules the author picks and tunes with one or two numbers."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from app.modules.lms.domain.badge_model import BadgeScope
from app.modules.lms.domain.badges import bad, parse_rule

TEMPLATE_CODES: Final = (
    "first_lesson",
    "section_master",
    "streak_7",
    "fast_finisher",
    "comeback",
    "coach_scholar",
)


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """One tunable number (or the section id) of a template."""

    name: str
    min: int | None
    max: int | None
    default: int | str | None


@dataclass(frozen=True, slots=True)
class BadgeTemplate:
    """A template: its code, its parameters and where it can be used."""

    code: str
    params: tuple[ParamSpec, ...]
    scope: BadgeScope


_COUNT = ParamSpec("count", 1, 1000, 5)
_TEMPLATES: Final = {
    "first_lesson": BadgeTemplate("first_lesson", (), BadgeScope.COURSE),
    "section_master": BadgeTemplate(
        "section_master",
        (ParamSpec("section_id", None, None, None), ParamSpec("pct", 50, 100, 90)),
        BadgeScope.COURSE,
    ),
    "streak_7": BadgeTemplate("streak_7", (), BadgeScope.COURSE),
    "fast_finisher": BadgeTemplate(
        "fast_finisher", (ParamSpec("days", 1, 365, 14),), BadgeScope.COURSE
    ),
    "comeback": BadgeTemplate("comeback", (_COUNT,), BadgeScope.COURSE),
    "coach_scholar": BadgeTemplate("coach_scholar", (_COUNT,), BadgeScope.PLATFORM),
}


def list_templates() -> list[BadgeTemplate]:
    """Return the catalogue in display order."""
    return [_TEMPLATES[code] for code in TEMPLATE_CODES]


def _number(params: Mapping[str, Any], spec: ParamSpec) -> int:
    value = params.get(spec.name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad(spec.name, "number-expected")
    if spec.min is not None and spec.max is not None:
        if not spec.min <= value <= spec.max:
            raise bad(spec.name, "number-out-of-range")
    return value


def _count_rule(event: str, count: int) -> dict[str, Any]:
    return {"event": event, "condition": {"op": "count_gte", "value": count}}


def compile_template(code: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Return the rule of a template; raise BadgeInvalidError on bad input."""
    template = _TEMPLATES.get(code)
    if template is None:
        raise bad("template", "unknown")
    values = {spec.name: params.get(spec.name) for spec in template.params}
    rule: dict[str, Any]
    if code == "first_lesson":
        rule = {"event": "step_completed", "condition": None}
    elif code == "section_master":
        section = values["section_id"]
        if not isinstance(section, str):
            raise bad("section_id", "required")
        pct = _number(params, template.params[1])
        rule = {
            "event": "section_completed",
            "condition": {
                "op": "and",
                "children": [
                    {"op": "section_is", "section_id": section},
                    {"op": "score_gte", "value": pct},
                ],
            },
        }
    elif code == "streak_7":
        rule = _count_rule("streak_reached", 7)
    elif code == "fast_finisher":
        days = _number(params, template.params[0])
        rule = {
            "event": "course_completed",
            "condition": {"op": "within_days_of_enroll", "value": days},
        }
    elif code == "comeback":
        rule = _count_rule("reviews_done", _number(params, template.params[0]))
    else:
        rule = _count_rule("coach_resolved", _number(params, template.params[0]))
    parse_rule(rule)
    return rule

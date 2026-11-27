"""The badge as a whole: scope, rule, template and version (platform or course)."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.modules.lms.domain.badges import (
    AGGREGATE_EVENTS,
    DESCRIPTION_MAX,
    NAME_MAX,
    AllOf,
    AnyOf,
    BadgeIcon,
    BadgeShape,
    Condition,
    CountAtLeast,
    Not,
    bad,
    clean_color,
    clean_texts,
    parse_rule,
)


class BadgeScope(StrEnum):
    """Where a badge lives: one course, or the whole platform."""

    COURSE = "course"
    PLATFORM = "platform"


def _only_counts(node: Condition | None) -> bool:
    """Return True when a condition reads nothing but running counts."""
    match node:
        case None | CountAtLeast():
            return True
        case AllOf(items) | AnyOf(items):
            return all(_only_counts(i) for i in items)
        case Not(item):
            return _only_counts(item)
    return False


@dataclass(frozen=True, slots=True)
class Badge:
    """A badge: texts, look, the rule JSON and where it applies."""

    id: UUID
    scope: BadgeScope
    course_id: UUID | None
    name: dict[str, str]
    description: dict[str, str]
    image: UUID | None
    rule: dict[str, Any]
    template_code: str | None
    template_params: dict[str, Any] | None
    enabled: bool
    version: int
    icon: BadgeIcon = BadgeIcon.STAR
    color: str = "#336699"
    shape: BadgeShape = BadgeShape.CIRCLE
    updated_at: datetime | None = None

    def validate(self) -> None:
        """Raise BadgeInvalidError unless the badge is consistent."""
        validate_rule(self.scope, self.rule)
        if self.scope is BadgeScope.COURSE and self.course_id is None:
            raise bad("course_id", "required")
        if self.scope is BadgeScope.PLATFORM and self.course_id is not None:
            raise bad("course_id", "not-allowed")
        clean_texts("name", self.name, NAME_MAX, required=True)
        clean_texts("description", self.description, DESCRIPTION_MAX, required=False)
        clean_color(self.color)

    def with_rule(self, rule: dict[str, Any], *, at: datetime) -> "Badge":
        """Return the badge with a new rule and the next version."""
        return replace(self, rule=rule, version=self.version + 1, updated_at=at)


def validate_rule(scope: BadgeScope, raw: Any) -> None:  # noqa: ANN401 - JSON
    """Parse the rule and check it fits the scope."""
    rule = parse_rule(raw)
    aggregate = rule.event in AGGREGATE_EVENTS
    if scope is BadgeScope.PLATFORM:
        if not aggregate:
            raise bad("rule", "platform-event-expected")
        if not _only_counts(rule.condition):
            raise bad("rule", "platform-counts-only")
    elif aggregate:
        raise bad("rule", "course-event-expected")

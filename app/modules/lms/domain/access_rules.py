"""Who may open a course or a lesson: the audience rule (LMS access rules).

A rule belongs to a course or to one of its steps. A step rule applies inside a
course the viewer may already open, so a lesson is never wider than its course.
Course staff and LMS administrators are never restricted.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

MAX_CHOSEN: Final = 500


class Audience(StrEnum):
    """Who may open the item."""

    PUBLIC = "public"
    SIGNED_IN = "signed_in"
    STUDENTS = "students"
    CHOSEN = "chosen"


class WhenDenied(StrEnum):
    """What the people outside the audience see."""

    HIDDEN = "hidden"
    LOCKED = "locked"


class AccessState(StrEnum):
    """The outcome of a rule for one viewer."""

    OPEN = "open"
    LOCKED = "locked"
    HIDDEN = "hidden"


@dataclass(frozen=True, slots=True)
class AccessRule:
    """The audience of a course or a step; the default admits everyone."""

    audience: Audience = Audience.PUBLIC
    when_denied: WhenDenied = WhenDenied.HIDDEN
    group_ids: tuple[UUID, ...] = ()
    user_ids: tuple[UUID, ...] = ()

    @property
    def is_open_to_all(self) -> bool:
        """Return True when the rule restricts nobody."""
        return self.audience is Audience.PUBLIC


PUBLIC_RULE: Final = AccessRule()


@dataclass(frozen=True, slots=True)
class Viewer:
    """The facts about the reader that rules look at; `user_id=None` is a guest."""

    user_id: UUID | None = None
    is_student: bool = False
    group_id: UUID | None = None
    bypass: bool = False


GUEST: Final = Viewer()


def admits(rule: AccessRule, viewer: Viewer) -> bool:
    """Return True if the viewer belongs to the audience of the rule."""
    if viewer.bypass or rule.audience is Audience.PUBLIC:
        return True
    if viewer.user_id is None:
        return False
    if rule.audience is Audience.SIGNED_IN:
        return True
    if rule.audience is Audience.STUDENTS:
        return viewer.is_student
    return viewer.user_id in rule.user_ids or (
        viewer.group_id is not None and viewer.group_id in rule.group_ids
    )


def decide(rule: AccessRule, viewer: Viewer) -> AccessState:
    """Return whether the viewer may open, sees a lock, or does not see the item."""
    if admits(rule, viewer):
        return AccessState.OPEN
    if rule.when_denied is WhenDenied.LOCKED:
        return AccessState.LOCKED
    return AccessState.HIDDEN


def combine(course: AccessState, step: AccessState) -> AccessState:
    """Return the state of a step inside a course: the stricter one wins."""
    order = (AccessState.OPEN, AccessState.LOCKED, AccessState.HIDDEN)
    return max(course, step, key=order.index)

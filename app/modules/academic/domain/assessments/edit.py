"""Editing a control: cleaning input, the audience and the patch."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal, TypeVar
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.assessments.errors import InvalidAssessmentError
from app.modules.academic.domain.assessments.periods import (
    CONTROL_KINDS,
    TermControls,
    infer_control,
)
from app.modules.academic.domain.assessments.records import (
    Assessment,
    AssessmentKind,
)
from app.modules.academic.domain.assessments.rules import status_after_edit
from app.modules.academic.domain.schedule.term import ControlName
from app.shared.clock import TASHKENT, to_local

TITLE_MAX = 200
ROOM_MAX = 120
NOTE_MAX = 2000
MAX_AUDIENCE = 20


class Unset:
    """Marks a patch field the caller did not send (None would mean "clear")."""

    __slots__ = ()


UNSET = Unset()
AudienceInput = Sequence[tuple[UUID, int | None]]
T = TypeVar("T")


def pick(value: T | Unset, default: T) -> T:
    """Return the patch value, or the current one when it was not sent."""
    return default if isinstance(value, Unset) else value


def clean_title(text: str) -> str:
    """Trim a title; empty is fine, too long is not."""
    cleaned = text.strip()
    if len(cleaned) > TITLE_MAX:
        raise InvalidAssessmentError(params={"field": "title", "max": TITLE_MAX})
    return cleaned


def clean_optional(text: str | None, field: str, limit: int) -> str | None:
    """Trim a free text; blank becomes None."""
    cleaned = (text or "").strip()
    if len(cleaned) > limit:
        raise InvalidAssessmentError(params={"field": field, "max": limit})
    return cleaned or None


def normalize_audience(pairs: AudienceInput) -> tuple[str, ...]:
    """Return sorted, unique audience keys; a whole group absorbs its subgroups."""
    if not pairs or len(pairs) > MAX_AUDIENCE:
        raise InvalidAssessmentError(params={"field": "audience"})
    whole = {group for group, sub in pairs if sub is None}
    keys = {
        audience_keys.key(group, sub)
        for group, sub in pairs
        if sub is None or group not in whole
    }
    return tuple(sorted(keys))


def resolve_control(
    kind: AssessmentKind,
    day: dt.date,
    terms: Sequence[TermControls],
    given: ControlName | None,
) -> ControlName | None:
    """Return the control week of a control: the one named, else the one it falls in.

    A named week must be of the same kind (a midterm cannot be the final).
    """
    if given is None:
        return infer_control(kind, day, terms)
    if CONTROL_KINDS[given] != kind:
        raise InvalidAssessmentError(params={"field": "control"})
    return given


def _on_day(starts_at: dt.datetime | None, day: dt.date) -> dt.datetime | None:
    """Return the same local time of day on another day (None stays None)."""
    if starts_at is None:
        return None
    local = to_local(starts_at)
    return dt.datetime.combine(day, local.timetz().replace(tzinfo=None), TASHKENT)


def check_starts_at(date: dt.date, starts_at: dt.datetime | None) -> None:
    """The start time must fall on the control's day (Tashkent time)."""
    if starts_at is not None and to_local(starts_at).date() != date:
        raise InvalidAssessmentError(params={"field": "starts_at"})


@dataclass(frozen=True, slots=True)
class AssessmentPatch:
    """A partial edit: fields left ``UNSET`` stay as they are, None clears."""

    subject_id: UUID | Unset = UNSET
    audience: AudienceInput | Unset = UNSET
    kind: AssessmentKind | Unset = UNSET
    title: str | Unset = UNSET
    date: dt.date | Unset = UNSET
    starts_at: dt.datetime | None | Unset = UNSET
    room: str | None | Unset = UNSET
    note: str | None | Unset = UNSET
    lesson_id: UUID | None | Unset = UNSET
    control: ControlName | None | Unset = UNSET
    status: Literal["planned", "cancelled"] | Unset = UNSET


def apply_patch(
    current: Assessment, patch: AssessmentPatch, terms: Sequence[TermControls] = ()
) -> Assessment:
    """Return the control with the patch applied.

    The control week follows the kind and date unless the patch names one.

    Changing anything but the status confirms a tentative control; an explicit
    ``planned`` confirms it as it is and ``cancelled`` dismisses it.
    """
    edited = replace(
        current,
        subject_id=pick(patch.subject_id, current.subject_id),
        audience=(
            current.audience
            if isinstance(patch.audience, Unset)
            else normalize_audience(patch.audience)
        ),
        kind=pick(patch.kind, current.kind),
        title=(
            current.title
            if isinstance(patch.title, Unset)
            else clean_title(patch.title)
        ),
        date=pick(patch.date, current.date),
        starts_at=pick(patch.starts_at, current.starts_at),
        room=(
            current.room
            if isinstance(patch.room, Unset)
            else clean_optional(patch.room, "room", ROOM_MAX)
        ),
        note=(
            current.note
            if isinstance(patch.note, Unset)
            else clean_optional(patch.note, "note", NOTE_MAX)
        ),
        lesson_id=pick(patch.lesson_id, current.lesson_id),
    )
    if isinstance(patch.starts_at, Unset) and edited.date != current.date:
        edited = replace(edited, starts_at=_on_day(current.starts_at, edited.date))
    check_starts_at(edited.date, edited.starts_at)
    moved = (edited.kind, edited.date) != (current.kind, current.date)
    if not isinstance(patch.control, Unset):
        control = resolve_control(edited.kind, edited.date, terms, patch.control)
    elif moved:
        control = resolve_control(edited.kind, edited.date, terms, None)
    else:
        control = current.control
    edited = replace(edited, control=control)
    requested = None if isinstance(patch.status, Unset) else patch.status
    changed = replace(edited, status=current.status) != current
    return replace(
        edited,
        status=status_after_edit(current.status, requested, changed=changed),
    )

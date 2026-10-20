"""Work-off tasks: templates, assignments and the rules around them (WO-1, WO-3)."""

import datetime as dt
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from uuid import UUID

from app.modules.academic.domain.classwork.errors import (
    WorkOffNotAbsentError,
    WorkOffStatusInvalidError,
    WorkOffTemplateLimitError,
    WorkOffTemplateNotFoundError,
    WorkOffTextInvalidError,
    WorkOffTextRequiredError,
)

TEMPLATE_TEXT_MAX: Final = 1000
WORK_OFF_TEXT_MAX: Final = 2000
TEMPLATE_LIMIT: Final = 20
STATUSES: Final = ("assigned", "done")

WorkOffMode = Literal["per_student", "none", "common"]
WorkOffStatus = Literal["assigned", "done"]


class Unset:
    """Marker type for "the field was not sent" (``None`` is a real value)."""


UNSET: Final = Unset()


def _iso(value: dt.date | dt.datetime | None) -> str | None:
    return None if value is None else value.isoformat()


@dataclass(frozen=True, slots=True)
class WorkOffTemplate:
    """A teacher's reusable work-off text; one of them may be the default."""

    id: UUID
    teacher_id: UUID
    text: str
    is_default: bool
    created_at: dt.datetime
    updated_at: dt.datetime

    def to_json(self) -> dict[str, Any]:
        """Return the ``WorkOffTemplateResponse`` fields."""
        return {
            "id": str(self.id),
            "text": self.text,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class WorkOff:
    """A work-off task given to one absent student for one lesson."""

    id: UUID
    lesson_id: UUID
    student_id: UUID
    assigned_by: UUID
    template_id: UUID | None
    text: str
    status: WorkOffStatus
    due_date: dt.date | None
    done_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime

    def to_json(self) -> dict[str, Any]:
        """Return the ``WorkOffResponse`` fields."""
        return {
            "id": str(self.id),
            "lesson_id": str(self.lesson_id),
            "student_id": str(self.student_id),
            "template_id": None if self.template_id is None else str(self.template_id),
            "text": self.text,
            "status": self.status,
            "due_date": _iso(self.due_date),
            "done_at": _iso(self.done_at),
            "assigned_by": str(self.assigned_by),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class WorkOffChoice:
    """What a teacher picked: a template, extra text and a due date."""

    template_id: UUID | None = None
    text: str | None = None
    due_date: dt.date | None = None


@dataclass(frozen=True, slots=True)
class WorkOffEntry:
    """A choice for one student (per-student mode)."""

    student_id: UUID
    choice: WorkOffChoice = field(default_factory=WorkOffChoice)


@dataclass(frozen=True, slots=True)
class ResolvedWorkOff:
    """A choice turned into the text that is saved."""

    text: str
    template_id: UUID | None
    due_date: dt.date | None


@dataclass(frozen=True, slots=True)
class WorkOffPlan:
    """Writes for one save: upserts by student and students whose task goes."""

    upserts: dict[UUID, ResolvedWorkOff]
    deletes: frozenset[UUID]


def _uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _date(value: Any) -> dt.date | None:
    if value is None or isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def as_choice(raw: WorkOffChoice | Mapping[str, Any] | None) -> WorkOffChoice | None:
    """Accept a choice or its JSON-like mapping (``template_id``, ``text``...)."""
    if raw is None or isinstance(raw, WorkOffChoice):
        return raw
    template = raw.get("template_id")
    return WorkOffChoice(
        template_id=None if template is None else _uuid(template),
        text=raw.get("text"),
        due_date=_date(raw.get("due_date")),
    )


def as_entry(raw: WorkOffEntry | Mapping[str, Any]) -> WorkOffEntry:
    """Accept an entry or its JSON-like mapping (with ``student_id``)."""
    if isinstance(raw, WorkOffEntry):
        return raw
    return WorkOffEntry(_uuid(raw["student_id"]), as_choice(raw) or WorkOffChoice())


def clean_template_text(text: str) -> str:
    """Strip a template text and check its length.

    Raises:
        WorkOffTextInvalidError: empty or longer than 1000 characters.
    """
    cleaned = text.strip()
    if not 1 <= len(cleaned) <= TEMPLATE_TEXT_MAX:
        raise WorkOffTextInvalidError(params={"max": TEMPLATE_TEXT_MAX})
    return cleaned


def ensure_template_capacity(existing_count: int) -> None:
    """Refuse a new template once the teacher has the maximum.

    Raises:
        WorkOffTemplateLimitError: the limit is reached.
    """
    if existing_count >= TEMPLATE_LIMIT:
        raise WorkOffTemplateLimitError(params={"max": TEMPLATE_LIMIT})


def defaults_to_clear(
    templates: Sequence[WorkOffTemplate], target_id: UUID | None, make_default: bool
) -> list[UUID]:
    """Ids whose default flag must go so the teacher keeps at most one default."""
    if not make_default:
        return []
    return [t.id for t in templates if t.is_default and t.id != target_id]


def resolve_text(template_text: str | None, extra: str | None) -> str | None:
    """Template text, a blank line, then the extra text; either may be missing.

    Raises:
        WorkOffTextInvalidError: the result is longer than 2000 characters.
    """
    parts = [p for p in ((template_text or "").strip(), (extra or "").strip()) if p]
    if not parts:
        return None
    text = "\n\n".join(parts)
    if len(text) > WORK_OFF_TEXT_MAX:
        raise WorkOffTextInvalidError(params={"max": WORK_OFF_TEXT_MAX})
    return text


def clean_text(text: str) -> str:
    """Strip an edited work-off text and check its length."""
    cleaned = text.strip()
    if not 1 <= len(cleaned) <= WORK_OFF_TEXT_MAX:
        raise WorkOffTextInvalidError(params={"max": WORK_OFF_TEXT_MAX})
    return cleaned


def ensure_status(status: str) -> WorkOffStatus:
    """Return the status or raise ``WorkOffStatusInvalidError``."""
    if status == "assigned":
        return "assigned"
    if status == "done":
        return "done"
    raise WorkOffStatusInvalidError(params={"status": status})


def referenced_template_ids(
    entries: Sequence[WorkOffEntry], common: WorkOffChoice | None
) -> list[UUID]:
    """Template ids a save mentions, without repeats."""
    ids = [e.choice.template_id for e in entries]
    ids.append(None if common is None else common.template_id)
    return list(dict.fromkeys(i for i in ids if i is not None))


def resolve_choice(
    choice: WorkOffChoice, template_texts: Mapping[UUID, str]
) -> ResolvedWorkOff | None:
    """Turn a choice into saved text, or None when it holds nothing.

    Raises:
        WorkOffTemplateNotFoundError: the template is not among the actor's own.
    """
    template_text = None
    if choice.template_id is not None:
        if choice.template_id not in template_texts:
            raise WorkOffTemplateNotFoundError(
                params={"template_id": str(choice.template_id)}
            )
        template_text = template_texts[choice.template_id]
    text = resolve_text(template_text, choice.text)
    if text is None:
        return None
    return ResolvedWorkOff(text, choice.template_id, choice.due_date)


def plan_work_offs(
    mode: WorkOffMode,
    absent: Collection[UUID],
    entries: Sequence[WorkOffEntry],
    common: WorkOffChoice | None,
    template_texts: Mapping[UUID, str],
) -> WorkOffPlan:
    """Decide the work-off writes of one attendance save (WO-3).

    Raises:
        WorkOffNotAbsentError: a listed student is not absent.
        WorkOffTextRequiredError: common mode without a resolvable text.
        WorkOffTemplateNotFoundError: an unknown template.
    """
    if mode == "none":
        return WorkOffPlan({}, frozenset())
    if mode == "common":
        resolved = None if common is None else resolve_choice(common, template_texts)
        if resolved is None:
            raise WorkOffTextRequiredError()
        return WorkOffPlan(dict.fromkeys(absent, resolved), frozenset())
    upserts: dict[UUID, ResolvedWorkOff] = {}
    deletes: set[UUID] = set()
    for entry in entries:
        if entry.student_id not in absent:
            raise WorkOffNotAbsentError(params={"user_ids": [str(entry.student_id)]})
        resolved = resolve_choice(entry.choice, template_texts)
        if resolved is None:
            deletes.add(entry.student_id)
        else:
            upserts[entry.student_id] = resolved
    return WorkOffPlan(upserts, frozenset(deletes))


def changed_students(
    existing: Mapping[UUID, WorkOff], upserts: Mapping[UUID, ResolvedWorkOff]
) -> set[UUID]:
    """Students whose work-off is new or has a different text."""
    return {
        student_id
        for student_id, new in upserts.items()
        if student_id not in existing or existing[student_id].text != new.text
    }


def notification_targets(
    previously_absent: Collection[UUID],
    absent: Collection[UUID],
    changed: Collection[UUID],
) -> dict[UUID, bool]:
    """Students to tell, with the ``update`` flag (WO-4).

    Newly absent students get the first notice (``False``); students who were
    already absent and got a new or edited work-off get an update (``True``).
    """
    targets = {s: False for s in absent if s not in previously_absent}
    for student_id in changed:
        if student_id in absent and student_id not in targets:
            targets[student_id] = True
    return targets

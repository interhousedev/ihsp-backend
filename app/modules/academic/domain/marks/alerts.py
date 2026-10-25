"""Notification drafts built from one student's sync (BOT-11 to BOT-14, ACA-22)."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.academic.domain.marks.diff import MarkKey
from app.modules.academic.domain.marks.records import ResultSnapshot
from app.modules.academic.domain.marks.results import drop_amount, formula_switched
from app.shared.contracts.emis import EmisMarkType
from app.shared.contracts.identity import UserPreferences
from app.shared.notifications import NotificationDraft, NotificationType

DROP_THRESHOLD = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class AddedMark:
    """A mark the sync saw for the first time."""

    subject_id: UUID
    subject_name: str
    semester: int
    key: MarkKey


@dataclass(frozen=True, slots=True)
class SubjectChange:
    """A subject's result before and after the sync."""

    subject_id: UUID
    subject_name: str
    semester: int
    old: ResultSnapshot | None
    new: ResultSnapshot


@dataclass(frozen=True, slots=True)
class GpaChange:
    """A semester GPA before and after the sync."""

    semester: int
    old: Decimal | None
    new: Decimal | None


def _num(value: Decimal | None) -> float | None:
    """Convert a decimal for a JSON payload."""
    return None if value is None else float(value)


def _text(value: Decimal | None) -> str:
    """Format a decimal for a dedupe key."""
    return "none" if value is None else f"{value:.2f}"


def _subject_wanted(prefs: UserPreferences, subject_id: UUID) -> bool:
    """Return True if the student follows this subject (None = all subjects)."""
    return prefs.marks_subject_ids is None or subject_id in prefs.marks_subject_ids


def _mark_wanted(prefs: UserPreferences, mark: AddedMark) -> bool:
    """Return True if the marks settings let this mark through (BOT-13)."""
    return (
        mark.key.type.value in prefs.marks_types
        and mark.key.value in prefs.marks_values
        and _subject_wanted(prefs, mark.subject_id)
    )


def _old_value(change: SubjectChange) -> Decimal | None:
    """Return the previous semester mark of a subject."""
    return None if change.old is None else change.old.value


def _mark_payload(mark: AddedMark) -> dict[str, Any]:
    return {
        "subject_id": str(mark.subject_id),
        "subject_name": mark.subject_name,
        "value": mark.key.value,
        "type": mark.key.type.value,
        "date": mark.key.date.isoformat(),
    }


def _change_payload(change: SubjectChange) -> dict[str, Any]:
    return {
        "subject_id": str(change.subject_id),
        "subject_name": change.subject_name,
        "old": _num(_old_value(change)),
        "new": _num(change.new.value),
    }


def _marks_notification(
    user_id: UUID,
    run_token: UUID,
    prefs: UserPreferences,
    added: Sequence[AddedMark],
    changes: Sequence[SubjectChange],
) -> NotificationDraft | None:
    """One `marks` notification per run, with the semester mark changes."""
    if not prefs.marks_enabled:
        return None
    shown = sorted(
        (m for m in added if _mark_wanted(prefs, m)),
        key=lambda m: (m.key.date, m.subject_name, m.key.type.value, m.key.ordinal),
    )
    if not shown:
        return None
    changed = [
        c
        for c in changes
        if _subject_wanted(prefs, c.subject_id)
        and c.new.value is not None
        and c.new.value != _old_value(c)
    ]
    payload = {
        "marks": [_mark_payload(m) for m in shown],
        "result_changes": [_change_payload(c) for c in changed],
    }
    return NotificationDraft(
        user_id=user_id,
        type=NotificationType.MARKS,
        payload=payload,
        dedupe_key=f"marks:{run_token}:{user_id}",
    )


def _gpa_drop(user_id: UUID, change: GpaChange) -> NotificationDraft | None:
    if drop_amount(change.old, change.new) < DROP_THRESHOLD:
        return None
    return NotificationDraft(
        user_id=user_id,
        type=NotificationType.RESULT_DROP,
        payload={
            "scope": "gpa",
            "semester": change.semester,
            "old": _num(change.old),
            "new": _num(change.new),
        },
        dedupe_key=f"drop:{user_id}:gpa:{change.semester}:{_text(change.new)}",
    )


def _subject_drop(user_id: UUID, change: SubjectChange) -> NotificationDraft | None:
    old = _old_value(change)
    if drop_amount(old, change.new.value) < DROP_THRESHOLD:
        return None
    if formula_switched(change.old, change.new):
        return None
    return NotificationDraft(
        user_id=user_id,
        type=NotificationType.RESULT_DROP,
        payload={
            "scope": "subject",
            "subject_id": str(change.subject_id),
            "subject_name": change.subject_name,
            "semester": change.semester,
            "old": _num(old),
            "new": _num(change.new.value),
        },
        dedupe_key=(
            f"drop:{user_id}:subject:{change.subject_id}:{change.semester}:"
            f"{_text(change.new.value)}"
        ),
    )


def _drop_alerts(
    user_id: UUID,
    prefs: UserPreferences,
    changes: Sequence[SubjectChange],
    gpa_changes: Sequence[GpaChange],
) -> list[NotificationDraft]:
    """`result_drop` for GPA and subject semester mark drops (ACA-22 applies)."""
    if not prefs.alerts_drops:
        return []
    drafts = [_gpa_drop(user_id, g) for g in gpa_changes]
    drafts += [
        _subject_drop(user_id, c)
        for c in changes
        if _subject_wanted(prefs, c.subject_id)
    ]
    return [d for d in drafts if d is not None]


def _crossed_down(old: Decimal | None, new: Decimal | None, limit: float) -> bool:
    """Return True if a value is below the limit now and was not before."""
    bound = Decimal(str(limit))
    if new is None or new >= bound:
        return False
    return old is None or old >= bound


def _below(
    user_id: UUID,
    scope: str,
    value: Decimal | float | int,
    threshold: float | int,
    dedupe: str,
    subject_name: str | None = None,
) -> NotificationDraft:
    payload: dict[str, Any] = {
        "scope": scope,
        "value": float(value),
        "threshold": float(threshold),
    }
    if subject_name is not None:
        payload["subject_name"] = subject_name
    return NotificationDraft(
        user_id=user_id,
        type=NotificationType.RESULT_BELOW,
        payload=payload,
        dedupe_key=f"below:{user_id}:{dedupe}",
    )


def _gpa_below(
    user_id: UUID, prefs: UserPreferences, gpa_changes: Sequence[GpaChange]
) -> list[NotificationDraft]:
    limit = prefs.alerts_gpa_below
    if limit is None:
        return []
    return [
        _below(user_id, "gpa", g.new, limit, f"gpa:{g.semester}:{_text(g.new)}")
        for g in gpa_changes
        if g.new is not None and _crossed_down(g.old, g.new, limit)
    ]


def _subject_below(
    user_id: UUID, prefs: UserPreferences, changes: Sequence[SubjectChange]
) -> list[NotificationDraft]:
    limit = prefs.alerts_semester_mark_below
    if limit is None:
        return []
    return [
        _below(
            user_id,
            "subject",
            c.new.value,
            limit,
            f"subject:{c.subject_id}:{c.semester}:{_text(c.new.value)}",
            c.subject_name,
        )
        for c in changes
        if c.new.value is not None
        and _subject_wanted(prefs, c.subject_id)
        and _crossed_down(_old_value(c), c.new.value, limit)
    ]


def _mark_below(
    user_id: UUID, prefs: UserPreferences, added: Sequence[AddedMark]
) -> list[NotificationDraft]:
    limit = prefs.alerts_mark_below
    if limit is None:
        return []
    return [
        _below(
            user_id,
            "mark",
            m.key.value,
            limit,
            (
                f"mark:{m.subject_id}:{m.semester}:{m.key.type.value}:"
                f"{m.key.date.isoformat()}:{m.key.value}:{m.key.ordinal}"
            ),
            m.subject_name,
        )
        for m in added
        if m.key.value < limit and _subject_wanted(prefs, m.subject_id)
    ]


def build_alerts(
    *,
    user_id: UUID,
    run_token: UUID,
    prefs: UserPreferences,
    added: Sequence[AddedMark],
    subject_changes: Sequence[SubjectChange],
    gpa_changes: Sequence[GpaChange],
) -> list[NotificationDraft]:
    """Build `marks`, `result_drop` and `result_below` drafts for one sync."""
    drafts: list[NotificationDraft] = []
    marks = _marks_notification(user_id, run_token, prefs, added, subject_changes)
    if marks is not None:
        drafts.append(marks)
    drafts += _drop_alerts(user_id, prefs, subject_changes, gpa_changes)
    drafts += _gpa_below(user_id, prefs, gpa_changes)
    drafts += _subject_below(user_id, prefs, subject_changes)
    drafts += _mark_below(user_id, prefs, added)
    return drafts


LOW_EXAM_VALUES = frozenset({2, 3})
EXAM_TYPES = frozenset({EmisMarkType.MIDTERM, EmisMarkType.FINAL})


def low_exam_marks(added: Sequence[AddedMark]) -> list[AddedMark]:
    """Return the new ПК (midterm) and ИК (final) marks of 2 or 3."""
    return [
        m for m in added if m.key.type in EXAM_TYPES and m.key.value in LOW_EXAM_VALUES
    ]


def curator_exam_alerts(
    *,
    curator_id: UUID,
    student_id: UUID,
    student_name: str,
    group_id: UUID,
    group_name: str,
    added: Sequence[AddedMark],
) -> list[NotificationDraft]:
    """One `curator_exam_mark` per low exam mark, for the student's curator."""
    return [
        NotificationDraft(
            user_id=curator_id,
            type=NotificationType.CURATOR_EXAM_MARK,
            payload={
                **_mark_payload(m),
                "semester": m.semester,
                "student_id": str(student_id),
                "student_name": student_name,
                "group_id": str(group_id),
                "group_name": group_name,
            },
            dedupe_key=(
                f"exam_low:{curator_id}:{student_id}:{m.subject_id}:{m.semester}:"
                f"{m.key.type.value}:{m.key.date.isoformat()}:{m.key.value}:"
                f"{m.key.ordinal}"
            ),
        )
        for m in low_exam_marks(added)
    ]

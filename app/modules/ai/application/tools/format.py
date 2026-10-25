"""Compact JSON shapes of academic data for the model."""

from datetime import date
from typing import Any

from app.shared.clock import to_local
from app.shared.contracts.academic import LessonRef, MarkRef

MAX_ROWS = 100


def day(value: date | None) -> str | None:
    """Return an ISO date or None."""
    return value.isoformat() if value is not None else None


def lesson_dict(ref: LessonRef) -> dict[str, Any]:
    """Return a lesson as the model sees it (times in Tashkent)."""
    return {
        "lesson_id": str(ref.id),
        "date": ref.date.isoformat(),
        "period": ref.period,
        "start": to_local(ref.starts_at).strftime("%H:%M"),
        "end": to_local(ref.ends_at).strftime("%H:%M"),
        "subject_id": str(ref.subject_id),
        "subject": ref.subject_name,
        "room": ref.room_name,
        "groups": list(ref.group_names),
        "status": ref.status,
        "topic": ref.topic,
        "homework": ref.homework_text,
        "homework_due": day(ref.homework_due_date),
    }


def mark_dict(ref: MarkRef) -> dict[str, Any]:
    """Return a mark as the model sees it."""
    return {
        "subject_id": str(ref.subject_id),
        "subject": ref.subject_name,
        "semester": ref.semester,
        "type": ref.type,
        "value": ref.value,
        "date": ref.date.isoformat(),
        "lesson_id": str(ref.lesson_id) if ref.lesson_id else None,
    }


def capped(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return `{"items": rows, "truncated": bool}` limited to MAX_ROWS rows."""
    return {"items": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS}

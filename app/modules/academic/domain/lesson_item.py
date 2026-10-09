"""The ``LessonItem`` JSON shape of the API contract (§ API contract -> Schemas)."""

from typing import Any

from app.shared.contracts.academic import LessonRef


def lesson_item(
    ref: LessonRef,
    *,
    teacher: dict[str, Any] | None,
    subject_short: str | None,
    audience: list[dict[str, Any]],
    attendance_submitted: bool,
    has_homework: bool,
    is_overridden: bool,
    changes: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the ``LessonItem`` dict of a lesson.

    Args:
        ref: The lesson as other modules see it.
        teacher: ``PersonRef`` dict ``{"id", "first_name", "last_name"}`` or None.
        subject_short: Short subject name; falls back to the full name when None.
        audience: ``AudienceItem`` dicts ``{"group_id", "group_name", "subgroup"}``.
        attendance_submitted: True once the attendance sheet was submitted.
        has_homework: True when the lesson has homework text.
        is_overridden: True when the lesson was changed by hand.
        changes: What was changed by hand, e.g. ``{"room": ["204", "310"]}``.
    """
    room = (
        {"id": str(ref.room_id), "slug": ref.room_slug, "name": ref.room_name}
        if ref.room_id is not None
        else None
    )
    return {
        "id": str(ref.id),
        "date": ref.date.isoformat(),
        "period": ref.period,
        "starts_at": ref.starts_at.isoformat(),
        "ends_at": ref.ends_at.isoformat(),
        "subject": {
            "id": str(ref.subject_id),
            "name": ref.subject_name,
            "short_name": subject_short or ref.subject_name,
        },
        "teacher": teacher,
        "room": room,
        "audience": audience,
        "status": ref.status,
        "is_overridden": is_overridden,
        "changes": changes,
        "topic": ref.topic,
        "kind": ref.kind,
        "topic_source": ref.topic_source,
        "has_homework": has_homework,
        "attendance_submitted": attendance_submitted,
    }

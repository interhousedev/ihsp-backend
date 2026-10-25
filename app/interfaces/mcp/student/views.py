"""JSON shapes of academic data returned by the Students server."""

from typing import Any

from app.shared.contracts.academic import LessonRef


def lesson_view(lesson: LessonRef) -> dict[str, Any]:
    """Return the fields of a lesson that matter to a student."""
    return {
        "id": lesson.id,
        "date": lesson.date,
        "period": lesson.period,
        "starts_at": lesson.starts_at,
        "ends_at": lesson.ends_at,
        "subject_id": lesson.subject_id,
        "subject_name": lesson.subject_name,
        "teacher_id": lesson.teacher_id,
        "room_name": lesson.room_name,
        "group_names": list(lesson.group_names),
        "status": lesson.status,
        "topic": lesson.topic,
        "homework_text": lesson.homework_text,
        "homework_due_date": lesson.homework_due_date,
    }


def with_lesson_view(item: dict[str, Any]) -> dict[str, Any]:
    """Replace the `lesson` entry of a classwork row by its student view."""
    lesson = item.get("lesson")
    if isinstance(lesson, LessonRef):
        return {**item, "lesson": lesson_view(lesson)}
    return item

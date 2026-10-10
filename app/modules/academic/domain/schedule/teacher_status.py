"""Which lesson a teacher is teaching now and which one comes next."""

import datetime as dt
from collections.abc import Iterable

from app.shared.contracts.academic import LessonRef


def current_and_next(
    lessons: Iterable[LessonRef], now: dt.datetime
) -> tuple[LessonRef | None, LessonRef | None]:
    """Return the running lesson and the next one to start (cancelled ones skipped).

    Args:
        lessons: The teacher's lessons in any order.
        now: The current aware moment.
    """
    live = sorted(
        (ref for ref in lessons if ref.status != "cancelled"),
        key=lambda ref: ref.starts_at,
    )
    current = next((ref for ref in live if ref.starts_at <= now < ref.ends_at), None)
    upcoming = next((ref for ref in live if ref.starts_at > now), None)
    return current, upcoming

"""A student's attendance state on one lesson, from the lesson's arrays."""

from collections.abc import Collection, Mapping
from typing import Any, Literal
from uuid import UUID

AttendanceState = Literal["present", "absent", "excused", "not_taken"]


def attendance_state(
    student_id: UUID,
    roster: Collection[UUID] | None,
    absent: Collection[UUID] | None,
    excused: Mapping[str, Any] | None,
) -> AttendanceState:
    """Return present, absent, excused or not_taken for one student."""
    if roster is None or absent is None or student_id not in roster:
        return "not_taken"
    if student_id not in absent:
        return "present"
    if excused is not None and str(student_id) in excused:
        return "excused"
    return "absent"

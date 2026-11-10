"""A student's attendance state on one lesson, from the lesson's arrays."""

from collections.abc import Collection
from typing import Literal
from uuid import UUID

AttendanceState = Literal["present", "late", "absent", "excused", "not_taken"]


def attendance_state(
    student_id: UUID,
    roster: Collection[UUID] | None,
    absent: Collection[UUID] | None,
    late: Collection[UUID] | None = None,
    *,
    excused: bool = False,
) -> AttendanceState:
    """Return present, late, absent, excused or not_taken for one student.

    ``excused`` is the unified rule: an excuse mark or an approved excuse.
    """
    if roster is None or absent is None or student_id not in roster:
        return "not_taken"
    if student_id not in absent:
        return "late" if late is not None and student_id in late else "present"
    if excused:
        return "excused"
    return "absent"

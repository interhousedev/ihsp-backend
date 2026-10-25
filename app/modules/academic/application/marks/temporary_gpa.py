"""The semester mark of subjects as if temporary lesson marks were in EMIS."""

import datetime as dt
from collections.abc import Collection
from uuid import UUID

from app.modules.academic.application.marks.ports.repositories import MarksReader
from app.modules.academic.application.marks.semester_range import semester_range
from app.modules.academic.domain.marks import grading
from app.modules.academic.domain.marks.read_models import StudentContext
from app.shared.clock import Clock, local_today

Window = tuple[dt.date | None, dt.date | None]


async def with_temporary(
    reader: MarksReader,
    student_ids: Collection[UUID],
    semester: int,
    window: Window | None,
) -> dict[tuple[UUID, UUID], float]:
    """Return `gpa_with_temporary` per (student, subject) that has temporary marks.

    Temporary marks count when their lesson date lies in the semester window
    (two queries for all students, none when the window is unknown).
    """
    if window is None or not student_ids:
        return {}
    temporary = await reader.temporary_values(student_ids, *window)
    if not temporary:
        return {}
    emis = await reader.mark_values({s for s, _subject in temporary}, semester)
    out: dict[tuple[UUID, UUID], float] = {}
    for key, values in temporary.items():
        by_type = emis.get(key, {})
        mark = grading.semester_mark_with_temporary(
            by_type.get("lesson", ()),
            by_type.get("midterm", ()),
            by_type.get("final", ()),
            values,
        )
        if mark is not None:
            out[key] = float(mark)
    return out


async def for_student(
    reader: MarksReader,
    ctx: StudentContext,
    semester: int,
    clock: Clock,
) -> dict[UUID, float]:
    """Return `gpa_with_temporary` per subject of one student."""
    window = await semester_range(reader, ctx, semester, local_today(clock))
    found = await with_temporary(reader, [ctx.user_id], semester, window)
    return {subject: value for (_student, subject), value in found.items()}

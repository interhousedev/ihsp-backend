"""The subjects of one semester of a student, as the semester pages show them."""

import datetime as dt
from collections.abc import Iterable
from uuid import UUID

from app.modules.academic.application.marks.ports.repositories import MarksReader
from app.modules.academic.domain.marks.read_models import ResultRow, StudentContext
from app.modules.academic.domain.marks.semester_subjects import semester_subject_ids


async def visible_subject_ids(
    reader: MarksReader,
    ctx: StudentContext,
    semester: int,
    results: Iterable[ResultRow],
    window: tuple[dt.date | None, dt.date | None] | None,
) -> set[UUID]:
    """Return the semester's subjects; `results` may hold other semesters too."""
    rows = [r for r in results if r.semester == semester]
    is_current = semester == ctx.current_semester
    candidates = {r.subject_id for r in rows if r.subject_id is not None}
    if is_current:
        candidates |= set(ctx.curriculum_subject_ids)
    taught = (
        {} if window is None else await reader.teacher_ids(ctx, candidates, *window)
    )
    return semester_subject_ids(
        rows=rows,
        planned=await reader.planned_subject_ids(ctx.group_id, semester),
        group_subjects=ctx.curriculum_subject_ids,
        taught=set(taught),
        is_current=is_current,
    )

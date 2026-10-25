"""Which dates a semester covers for one student."""

import datetime as dt

from app.modules.academic.application.marks.ports.repositories import MarksReader
from app.modules.academic.domain.marks.read_models import StudentContext
from app.modules.academic.domain.marks.semesters import semester_window


async def semester_range(
    reader: MarksReader, ctx: StudentContext, semester: int, today: dt.date
) -> tuple[dt.date | None, dt.date | None] | None:
    """Return (start, end) of the semester; (None, None) if unknown but current.

    Returns None for a past semester whose term is not in the calendar.
    """
    window = semester_window(
        await reader.terms(), ctx.current_semester, semester, today
    )
    if window is not None:
        return window
    if semester == ctx.current_semester:
        return None, None
    return None

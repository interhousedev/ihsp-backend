"""Task academic.sync_student_all: a student's curriculum, timetable and marks.

Kicked after a registration (the marks come from `academic.backfill_student` then) and
by the settings button `POST /v1/me/sync` (with the marks).
"""

from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.sync_student_all")
async def sync_student_all(user_id: UUID, with_marks: bool = False) -> str:
    """Run the sync in order; return the timetable status."""
    container: Container = get_container()
    return await container.academic.emis_import.sync_student_all.execute(
        user_id, with_marks=with_marks
    )

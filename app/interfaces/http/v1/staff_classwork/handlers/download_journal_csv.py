"""``GET /v1/staff/journal.csv``: the journal as a spreadsheet (STF-9)."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, TeacherActor

from fastapi import Response


async def download_journal_csv(
    subject_id: UUID,
    audience_key: str,
    actor: TeacherActor,
    container: ContainerDep,
    term_id: UUID | None = None,
) -> Response:
    """Return the grid as CSV (UTF-8 with BOM, ``;`` separated)."""
    data = await container.academic.classwork.journal_csv.execute(
        actor, subject_id, audience_key, term_id
    )
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="journal.csv"'},
    )

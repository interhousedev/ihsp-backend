"""``GET /v1/staff/journal``: the journal grid (STF-9)."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, TeacherActor
from app.interfaces.http.v1.staff_classwork.schemas import JournalResponse


async def get_journal(
    subject_id: UUID,
    audience_key: str,
    actor: TeacherActor,
    container: ContainerDep,
    term_id: UUID | None = None,
) -> JournalResponse:
    """Return students by lessons with absences and marks."""
    data = await container.academic.classwork.get_journal.execute(
        actor, subject_id, audience_key, term_id
    )
    return JournalResponse.model_validate(data)

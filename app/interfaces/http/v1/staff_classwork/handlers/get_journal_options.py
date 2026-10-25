"""``GET /v1/staff/journal/options``: journals the teacher can open (STF-9)."""

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, TeacherActor
from app.interfaces.http.v1.staff_classwork.schemas import JournalOptionResponse


async def get_journal_options(
    actor: TeacherActor, container: ContainerDep
) -> list[JournalOptionResponse]:
    """Return the subject and audience pairs of the current term."""
    data = await container.academic.classwork.journal_options.execute(actor)
    return [JournalOptionResponse.model_validate(item) for item in data]

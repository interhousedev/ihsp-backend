"""GET /v1/admin/subjects."""

from typing import Annotated

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.subjects.schemas import SubjectResponse

from fastapi import Query


async def list_subjects(
    container: ContainerDep,
    actor: AdminActor,
    query: Annotated[str | None, Query(max_length=100)] = None,
) -> list[SubjectResponse]:
    """List subjects, optionally filtered by a name fragment."""
    subjects = await container.academic.schedule.list_subjects.execute(query)
    return [SubjectResponse.model_validate(subject) for subject in subjects]

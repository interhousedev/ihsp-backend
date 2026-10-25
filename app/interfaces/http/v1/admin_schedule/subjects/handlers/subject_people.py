"""GET /v1/admin/subjects/{id}/people."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.subjects.schemas import (
    SubjectPeopleResponse,
    SubjectPersonResponse,
)


async def subject_people(
    subject_id: UUID, container: ContainerDep, actor: AdminActor
) -> SubjectPeopleResponse:
    """Teachers and groups that have the subject in the current term."""
    found = await container.academic.schedule.get_subject_people.execute(subject_id)
    return SubjectPeopleResponse(
        teachers=[SubjectPersonResponse(id=t.id, name=t.name) for t in found.teachers],
        groups=[SubjectPersonResponse(id=g.id, name=g.name) for g in found.groups],
    )

"""POST /v1/admin/subjects."""

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.subjects.schemas import (
    SubjectCreateBody,
    SubjectResponse,
)


async def create_subject(
    body: SubjectCreateBody, container: ContainerDep, actor: AdminActor
) -> SubjectResponse:
    """Add a subject."""
    subject = await container.academic.schedule.create_subject.execute(
        name=body.name.model_dump(),
        short_name=body.short_name,
        emis_subject_id=body.emis_subject_id,
        can_be_divided=body.can_be_divided,
    )
    return SubjectResponse.model_validate(subject)

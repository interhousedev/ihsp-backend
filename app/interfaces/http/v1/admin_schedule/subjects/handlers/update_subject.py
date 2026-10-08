"""PATCH /v1/admin/subjects/{id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.subjects.schemas import (
    SubjectPatchBody,
    SubjectResponse,
)
from app.modules.academic.application.schedule.unset import UNSET


async def update_subject(
    subject_id: UUID,
    body: SubjectPatchBody,
    container: ContainerDep,
    actor: AdminActor,
) -> SubjectResponse:
    """Change a subject; null clears the short name or the EMIS link."""
    sent = body.model_fields_set
    subject = await container.academic.schedule.update_subject.execute(
        subject_id,
        name=body.name.model_dump() if body.name is not None else None,
        short_name=body.short_name if "short_name" in sent else UNSET,
        emis_subject_id=body.emis_subject_id if "emis_subject_id" in sent else UNSET,
        can_be_divided=body.can_be_divided,
    )
    return SubjectResponse.model_validate(subject)

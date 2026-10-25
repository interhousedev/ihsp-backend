"""PATCH /v1/admin/groups/{id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.admin_schedule.groups.schemas import (
    GroupDetailResponse,
    GroupPatchBody,
)
from app.modules.academic.application.schedule.unset import UNSET


async def update_group(
    group_id: UUID,
    body: GroupPatchBody,
    container: ContainerDep,
    actor: AdminActor,
) -> GroupDetailResponse:
    """Set the curator, head student or status; null clears curator and head."""
    sent = body.model_fields_set
    detail = await container.academic.schedule.update_group.execute(
        actor,
        group_id,
        curator_id=body.curator_id if "curator_id" in sent else UNSET,
        head_student_id=body.head_student_id if "head_student_id" in sent else UNSET,
        status=body.status,
        name=body.name,
        current_semester=body.current_semester,
    )
    return GroupDetailResponse.model_validate(detail)

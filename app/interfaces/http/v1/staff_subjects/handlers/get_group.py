"""GET /v1/staff/subjects/{subject_id}/groups/{group_id}[/subgroups/{subgroup}]."""

from uuid import UUID

from app.interfaces.http.v1.staff_subjects.deps import (
    ContainerDep,
    StaffActor,
    SubgroupPath,
)
from app.interfaces.http.v1.staff_subjects.schemas import TeachingGroupResponse


async def get_group(
    subject_id: UUID, group_id: UUID, container: ContainerDep, actor: StaffActor
) -> TeachingGroupResponse:
    """A group the caller teaches the subject: students and lessons."""
    view = await container.academic.teaching.get_group.execute(
        actor, subject_id, group_id, None
    )
    return TeachingGroupResponse.from_view(view)


async def get_subgroup(
    subject_id: UUID,
    group_id: UUID,
    subgroup: SubgroupPath,
    container: ContainerDep,
    actor: StaffActor,
) -> TeachingGroupResponse:
    """A subgroup the caller teaches the subject: its students and lessons."""
    view = await container.academic.teaching.get_group.execute(
        actor, subject_id, group_id, subgroup
    )
    return TeachingGroupResponse.from_view(view)

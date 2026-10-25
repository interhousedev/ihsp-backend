"""GET .../groups/{group_id}[/subgroups/{n}]/students/{student_id}."""

from uuid import UUID

from app.interfaces.http.v1.staff_subjects.deps import (
    ContainerDep,
    StaffActor,
    SubgroupPath,
)
from app.interfaces.http.v1.staff_subjects.schemas import TeachingStudentResponse


async def get_student(
    subject_id: UUID,
    group_id: UUID,
    student_id: UUID,
    container: ContainerDep,
    actor: StaffActor,
) -> TeachingStudentResponse:
    """A student's marks, homework and attendance in the subject."""
    view = await container.academic.teaching.get_student.execute(
        actor, subject_id, group_id, student_id, None
    )
    return TeachingStudentResponse.model_validate(view)


async def get_subgroup_student(
    subject_id: UUID,
    group_id: UUID,
    subgroup: SubgroupPath,
    student_id: UUID,
    container: ContainerDep,
    actor: StaffActor,
) -> TeachingStudentResponse:
    """A student of a subgroup: marks, homework and attendance in the subject."""
    view = await container.academic.teaching.get_student.execute(
        actor, subject_id, group_id, student_id, subgroup
    )
    return TeachingStudentResponse.model_validate(view)

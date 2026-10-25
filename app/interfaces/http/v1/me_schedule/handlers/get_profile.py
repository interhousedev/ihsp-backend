"""GET /v1/me/profile."""

from app.interfaces.http.v1.me_schedule.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.me_schedule.schemas import StudentProfileResponse


async def get_profile(
    container: ContainerDep, actor: StudentActor
) -> StudentProfileResponse:
    """Return the student's group, subgroup, curator and mailbox."""
    data = await container.academic.schedule.get_student_profile.execute(actor)
    return StudentProfileResponse.from_data(data)

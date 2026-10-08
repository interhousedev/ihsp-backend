"""``GET /v1/staff/today``: the teacher's Today page (STF-2)."""

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, TeacherActor
from app.interfaces.http.v1.staff_classwork.schemas import StaffTodayResponse


async def get_today(actor: TeacherActor, container: ContainerDep) -> StaffTodayResponse:
    """Return the current or next lesson, today's lessons and what was missed."""
    data = await container.academic.classwork.staff_today.execute(actor)
    return StaffTodayResponse.model_validate(data)

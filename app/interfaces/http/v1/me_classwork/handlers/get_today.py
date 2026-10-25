"""``GET /v1/me/today``: the student's Today dashboard (WEB-3)."""

from app.interfaces.http.v1.me_classwork.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.me_classwork.schemas import StudentTodayResponse


async def get_today(
    actor: StudentActor, container: ContainerDep
) -> StudentTodayResponse:
    """Return now and next lesson, the timeline, due homework, marks, semester."""
    data = await container.academic.classwork.student_today.execute(actor)
    return StudentTodayResponse.model_validate(data)

"""``GET /v1/me/work-offs``: the student's own work-off tasks (WO-6)."""

from typing import Literal

from app.interfaces.http.v1.me_classwork.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.me_classwork.schemas import MyWorkOffResponse


async def list_my_work_offs(
    actor: StudentActor,
    container: ContainerDep,
    status: Literal["open", "all"] = "open",
) -> list[MyWorkOffResponse]:
    """Return the student's work-offs, newest lesson first."""
    data = await container.academic.classwork.list_my_work_offs.execute(
        actor.user_id, status=status
    )
    return [MyWorkOffResponse.model_validate(item) for item in data]

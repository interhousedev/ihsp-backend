"""``GET /v1/me/homework``: overdue, upcoming, later and done homework (WEB-18)."""

from typing import Literal

from app.interfaces.http.v1.me_classwork.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.me_classwork.schemas import HomeworkItemResponse


async def list_homework(
    actor: StudentActor,
    container: ContainerDep,
    status: Literal["overdue", "upcoming", "later", "done"] = "upcoming",
) -> list[HomeworkItemResponse]:
    """Return the chosen list; ``upcoming`` is the default."""
    data = await container.academic.classwork.homework_list.execute(actor, status)
    return [HomeworkItemResponse.model_validate(item) for item in data]

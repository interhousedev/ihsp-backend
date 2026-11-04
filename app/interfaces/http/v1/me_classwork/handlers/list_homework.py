"""``GET /v1/me/homework``: overdue, upcoming, later and done homework (WEB-18)."""

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.me_classwork.deps import ContainerDep, StudentActor
from app.interfaces.http.v1.me_classwork.schemas import HomeworkItemResponse

from fastapi import Query


async def list_homework(
    actor: StudentActor,
    container: ContainerDep,
    status: Literal["overdue", "upcoming", "later", "done"] = "upcoming",
    subject_id: UUID | None = None,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
) -> list[HomeworkItemResponse]:
    """Return the chosen list; ``upcoming`` is the default.

    ``subject_id`` keeps one subject; ``from`` and ``to`` keep the homework due in
    that range (inclusive), by due date.
    """
    data = await container.academic.classwork.homework_list.execute(
        actor,
        status,
        subject_id=subject_id,
        date_from=date_from,
        date_to=date_to,
    )
    return [HomeworkItemResponse.model_validate(item) for item in data]

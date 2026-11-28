"""``GET /v1/staff/homework``: the homework board of one journal option."""

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import StaffHomeworkBoardResponse

from fastapi import Query


async def get_homework_board(
    subject_id: UUID,
    audience_key: str,
    actor: StaffActor,
    container: ContainerDep,
    start: Annotated[dt.date | None, Query(alias="from")] = None,
    end: Annotated[dt.date | None, Query(alias="to")] = None,
    only: Literal["all", "with_homework", "to_review"] = "all",
) -> StaffHomeworkBoardResponse:
    """Return the lessons with homework, switches and counts; current term by default.

    404 when the option is not the teacher's or there is no current term.
    """
    data = await container.academic.classwork.homework_board.execute(
        actor, subject_id, audience_key, date_from=start, date_to=end, only=only
    )
    return StaffHomeworkBoardResponse.model_validate(data)

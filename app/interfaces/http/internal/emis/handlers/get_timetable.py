"""GET /internal/emis/{user_id}/timetable?begin=&end=."""

import datetime as dt
from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.internal.emis.schemas import EmisClassResponse

from fastapi import Depends, HTTPException, Query

MAX_DAYS = 62


async def get_timetable(
    user_id: UUID,
    begin: Annotated[dt.date, Query()],
    end: Annotated[dt.date, Query()],
    container: Annotated[Container, Depends(get_container)],
) -> list[EmisClassResponse]:
    """Return the student's classes on the dates begin..end (one EMIS call a week)."""
    if end < begin or (end - begin).days >= MAX_DAYS:
        raise HTTPException(status_code=422, detail="begin..end must be 1-62 days")
    items = await container.identity.emis.gateway.timetable(user_id, begin, end)
    return [EmisClassResponse.from_contract(item) for item in items]

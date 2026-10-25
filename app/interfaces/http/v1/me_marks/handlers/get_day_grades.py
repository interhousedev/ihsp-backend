"""GET /v1/me/grades/day."""

import datetime as dt
from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def get_day_grades(
    day: Annotated[dt.date, Query(alias="date")],
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    """Return the marks of one date placed on their lessons."""
    grades: dict[str, Any] = await container.academic.marks.get_day_grades.execute(
        actor, day
    )
    return grades

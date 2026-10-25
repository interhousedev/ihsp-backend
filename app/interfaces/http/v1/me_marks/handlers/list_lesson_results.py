"""GET /v1/me/lesson-results?from=&to=."""

import datetime as dt
from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def list_lesson_results(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
    start: Annotated[dt.date, Query(alias="from")],
    end: Annotated[dt.date, Query(alias="to")],
) -> list[dict[str, Any]]:
    """Return attendance and the mark of each lesson that has already started."""
    rows: list[dict[str, Any]] = (
        await container.academic.marks.list_lesson_results.execute(actor, start, end)
    )
    return rows

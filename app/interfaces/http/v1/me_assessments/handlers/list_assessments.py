"""GET /v1/me/assessments."""

import datetime as dt
from typing import Annotated, Any
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def list_assessments(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
    since: Annotated[dt.date | None, Query(alias="from")] = None,
    until: Annotated[dt.date | None, Query(alias="to")] = None,
    subject_id: UUID | None = None,
) -> dict[str, Any]:
    """Return the controls of the student's group, soonest first."""
    items = await container.academic.assessments.list_mine.execute(
        actor, since=since, until=until, subject_id=subject_id
    )
    return {"items": items}

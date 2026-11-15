"""GET /v1/me/academic/control-periods."""

import datetime as dt
from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def list_control_periods(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
    since: Annotated[dt.date | None, Query(alias="from")] = None,
    until: Annotated[dt.date | None, Query(alias="to")] = None,
) -> dict[str, Any]:
    """Return the control weeks with the exams left and the marks taken."""
    items = await container.academic.assessments.list_control_periods.execute(
        actor, since=since, until=until
    )
    return {"items": items}

"""GET /v1/staff/assessments."""

from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.staff_assessments.mapping import filters
from app.modules.academic.application.assessments.inputs import StaffFilters
from app.shared.actor import Actor, Role

from fastapi import Depends


async def list_assessments(
    actor: Annotated[Actor, Depends(require_roles(Role.TEACHER, Role.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
    query: Annotated[StaffFilters, Depends(filters)],
) -> dict[str, Any]:
    """Return the controls of the teacher's subjects and groups (all for admin)."""
    items = await container.academic.assessments.list_staff.execute(actor, query)
    return {"items": items}

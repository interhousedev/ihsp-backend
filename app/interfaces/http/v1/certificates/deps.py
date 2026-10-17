"""Dependencies of the certificates routes."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container, require_roles
from app.modules.certificates.application.staff_scope import StaffFilters
from app.shared.actor import Actor, Role

from fastapi import Depends

ContainerDep = Annotated[Container, Depends(get_container)]
AnyActor = Annotated[Actor, Depends(get_actor)]
StudentActor = Annotated[Actor, Depends(require_roles(Role.STUDENT))]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]
StaffActor = Annotated[Actor, Depends(require_roles(Role.ADMIN, Role.TEACHER))]


def staff_filters(
    group_id: UUID | None = None,
    subgroup: str | None = None,
    type_id: UUID | None = None,
    subject: str | None = None,
    level: str | None = None,
    student_id: UUID | None = None,
    q: str | None = None,
) -> StaffFilters:
    """Read the staff filters from the query string."""
    return StaffFilters(
        group_id=group_id,
        subgroup=subgroup,
        type_id=type_id,
        subject=subject,
        level=level,
        student_id=student_id,
        q=q,
    )


FiltersDep = Annotated[StaffFilters, Depends(staff_filters)]

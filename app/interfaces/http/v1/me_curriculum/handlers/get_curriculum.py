"""GET /v1/me/curriculum."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_schedule.groups.curriculum_schemas import (
    CurriculumResponse,
)
from app.shared.actor import Actor, Role

from fastapi import Depends


async def get_curriculum(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
) -> CurriculumResponse | None:
    """Return the curriculum of the student's group, or null when none is stored."""
    view = await container.academic.schedule.get_my_curriculum.execute(actor)
    return CurriculumResponse.model_validate(view) if view else None

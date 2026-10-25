"""GET /v1/me/grades."""

from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Query


async def get_grades(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
    semester: Annotated[int | None, Query(ge=1, le=4)] = None,
) -> dict[str, Any]:
    """Return the grade table and GPA of a semester."""
    grades: dict[str, Any] = await container.academic.marks.get_semester_grades.execute(
        actor, semester
    )
    return grades

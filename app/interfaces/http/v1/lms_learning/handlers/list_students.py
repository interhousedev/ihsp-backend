"""GET /v1/lms/courses/{id}/students: students with progress and attempts."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.modules.lms.application.learning.views import LearningCourseStudentView
from app.shared.actor import Actor

from fastapi import Depends, Response


async def list_students(
    course_id: UUID,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> list[LearningCourseStudentView]:
    """List enrolled students; needs the `review` permission."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    students: list[LearningCourseStudentView] = (
        await container.lms.learning.list_course_students.execute(actor, course_id)
    )
    return students

"""DELETE /v1/lms/courses/{id}/staff/{user_id}: remove a staff member."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep


async def remove_staff(
    course_id: UUID, user_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> None:
    """Remove the member; the last manager can only be removed by an LMS admin."""
    await authoring.remove_course_staff.execute(actor, course_id, user_id)

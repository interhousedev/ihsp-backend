"""``DELETE /v1/me/homework/{lesson_id}/submission``: withdraw it."""

from uuid import UUID

from app.interfaces.http.v1.me_classwork.deps import ContainerDep, StudentActor

from fastapi import Response


async def withdraw_homework_submission(
    lesson_id: UUID, actor: StudentActor, container: ContainerDep
) -> Response:
    """Delete the caller's submission; the files stay in their storage."""
    await container.academic.classwork.withdraw_homework_submission.execute(
        lesson_id, actor
    )
    return Response(status_code=204)

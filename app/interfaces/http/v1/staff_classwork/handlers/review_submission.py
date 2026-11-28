"""``/v1/staff/homework/submissions/{submission_id}``: open, review, clear review."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import (
    ReviewBody,
    StaffSubmissionRowResponse,
)

from fastapi import Response


async def get_homework_submission(
    submission_id: UUID, actor: StaffActor, container: ContainerDep
) -> StaffSubmissionRowResponse:
    """Return one submission with time-limited file links."""
    data = await container.academic.classwork.get_staff_homework_submission.execute(
        submission_id, actor
    )
    return StaffSubmissionRowResponse.model_validate(data)


async def review_homework_submission(
    submission_id: UUID, body: ReviewBody, actor: StaffActor, container: ContainerDep
) -> StaffSubmissionRowResponse:
    """Grade the work (also a temporary mark) or return it with a comment."""
    data = await container.academic.classwork.review_homework_submission.execute(
        submission_id,
        actor,
        action=body.action,
        grade=body.grade,
        comment=body.comment,
    )
    return StaffSubmissionRowResponse.model_validate(data)


async def clear_homework_review(
    submission_id: UUID, actor: StaffActor, container: ContainerDep
) -> Response:
    """Put the submission back to pending and delete the grade's mark."""
    await container.academic.classwork.clear_homework_review.execute(
        submission_id, actor
    )
    return Response(status_code=204)

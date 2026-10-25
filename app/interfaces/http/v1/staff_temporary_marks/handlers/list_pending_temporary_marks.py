"""``GET /v1/staff/temporary-marks/pending``: marks not in EMIS yet (TMP-3)."""

from uuid import UUID

from app.interfaces.http.v1.staff_temporary_marks.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_temporary_marks.schemas import (
    TemporaryMarkListResponse,
)


async def list_pending_temporary_marks(
    actor: StaffActor, container: ContainerDep, teacher_id: UUID | None = None
) -> TemporaryMarkListResponse:
    """The caller's pending marks; Administration may pick a teacher or see all."""
    views = await container.academic.classwork.list_pending_temporary_marks.execute(
        actor, teacher_id=teacher_id
    )
    return TemporaryMarkListResponse.model_validate(
        {"items": [view.to_json() for view in views]}
    )

"""``PATCH /v1/staff/work-offs/{id}``: edit text, due date or status (WO-3)."""

from uuid import UUID

from app.interfaces.http.v1.staff_classwork.schemas import WorkOffResponse
from app.interfaces.http.v1.staff_work_offs.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_work_offs.schemas import WorkOffPatchBody
from app.modules.academic.domain.classwork.work_off import UNSET


async def update_work_off(
    id: UUID, body: WorkOffPatchBody, actor: StaffActor, container: ContainerDep
) -> WorkOffResponse:
    """Apply the sent fields; an absent ``due_date`` stays, ``null`` clears it."""
    sent = body.model_fields_set
    item = await container.academic.classwork.update_work_off.execute(
        id,
        actor,
        text=body.text,
        due_date=body.due_date if "due_date" in sent else UNSET,
        status=body.status,
    )
    return WorkOffResponse.model_validate(item.to_json())

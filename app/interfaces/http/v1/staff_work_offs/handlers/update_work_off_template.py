"""``PUT /v1/staff/work-off-templates/{id}``: change a template (WO-1)."""

from uuid import UUID

from app.interfaces.http.v1.staff_work_offs.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_work_offs.schemas import (
    WorkOffTemplateBody,
    WorkOffTemplateResponse,
)


async def update_work_off_template(
    id: UUID, body: WorkOffTemplateBody, actor: StaffActor, container: ContainerDep
) -> WorkOffTemplateResponse:
    """Save one of the actor's templates."""
    item = await container.academic.classwork.update_work_off_template.execute(
        actor, id, body.text, body.is_default
    )
    return WorkOffTemplateResponse.model_validate(item.to_json())

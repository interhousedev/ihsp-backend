"""``POST /v1/staff/work-off-templates``: add a template (WO-1)."""

from app.interfaces.http.v1.staff_work_offs.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_work_offs.schemas import (
    WorkOffTemplateBody,
    WorkOffTemplateResponse,
)


async def create_work_off_template(
    body: WorkOffTemplateBody, actor: StaffActor, container: ContainerDep
) -> WorkOffTemplateResponse:
    """Create a template for the actor."""
    item = await container.academic.classwork.create_work_off_template.execute(
        actor, body.text, body.is_default
    )
    return WorkOffTemplateResponse.model_validate(item.to_json())

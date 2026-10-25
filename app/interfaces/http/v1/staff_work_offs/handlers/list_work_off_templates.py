"""``GET /v1/staff/work-off-templates``: the teacher's own templates (WO-1)."""

from app.interfaces.http.v1.staff_work_offs.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_work_offs.schemas import WorkOffTemplateResponse


async def list_work_off_templates(
    actor: StaffActor, container: ContainerDep
) -> list[WorkOffTemplateResponse]:
    """Return the actor's templates, oldest first."""
    items = await container.academic.classwork.list_work_off_templates.execute(
        actor.user_id
    )
    return [WorkOffTemplateResponse.model_validate(i.to_json()) for i in items]

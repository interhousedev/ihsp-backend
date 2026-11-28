"""``GET|PUT /v1/staff/homework/settings``: the teacher's own homework settings."""

from app.interfaces.http.v1.staff_classwork.deps import ContainerDep, StaffActor
from app.interfaces.http.v1.staff_classwork.schemas import (
    HomeworkSettingsBody,
    HomeworkSettingsResponse,
)


async def get_homework_settings(
    actor: StaffActor, container: ContainerDep
) -> HomeworkSettingsResponse:
    """Return whether new homework accepts submissions and notifies by default."""
    data = await container.academic.classwork.get_homework_settings.execute(actor)
    return HomeworkSettingsResponse.model_validate(data)


async def save_homework_settings(
    body: HomeworkSettingsBody, actor: StaffActor, container: ContainerDep
) -> HomeworkSettingsResponse:
    """Save the given settings; an omitted field keeps its value."""
    data = await container.academic.classwork.save_homework_settings.execute(
        actor,
        accept_by_default=body.accept_by_default,
        notify_on_submission=body.notify_on_submission,
    )
    return HomeworkSettingsResponse.model_validate(data)

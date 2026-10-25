"""GET /v1/certificates/staff/fields/{key}/values."""

from app.interfaces.http.v1.certificates.deps import (
    ContainerDep,
    FiltersDep,
    StaffActor,
)
from app.interfaces.http.v1.certificates.schemas import CustomFieldValuesResponse


async def list_custom_field_values(
    key: str, container: ContainerDep, actor: StaffActor, filters: FiltersDep
) -> CustomFieldValuesResponse:
    """Return the choices and stored values of one custom field of the type."""
    values = await container.certificates.list_custom_field_values.execute(
        actor, filters, key
    )
    return CustomFieldValuesResponse.from_values(values)

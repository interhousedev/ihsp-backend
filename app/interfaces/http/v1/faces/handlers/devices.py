"""Administrators' routes for entrance devices."""

from uuid import UUID

from app.interfaces.http.v1.faces.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.faces.schemas import (
    DeviceCallListOut,
    DeviceCallOut,
    DeviceCreatedOut,
    DeviceCreateIn,
    DeviceListOut,
    DeviceOut,
)


async def list_devices(container: ContainerDep, actor: AdminActor) -> DeviceListOut:
    """Every device, newest first."""
    devices = await container.faces.list_devices.execute()
    return DeviceListOut(items=[DeviceOut.of(d) for d in devices])


async def create_device(
    body: DeviceCreateIn, container: ContainerDep, actor: AdminActor
) -> DeviceCreatedOut:
    """Create a device; the token is in this response only."""
    created = await container.faces.create_device.execute(actor.user_id, body.name)
    return DeviceCreatedOut.of(created)


async def revoke_device(
    device_id: UUID, container: ContainerDep, actor: AdminActor
) -> DeviceOut:
    """Stop the device's token from working."""
    return DeviceOut.of(await container.faces.revoke_device.execute(device_id))


async def list_device_calls(
    device_id: UUID, container: ContainerDep, actor: AdminActor
) -> DeviceCallListOut:
    """The device's requests of the last 7 days."""
    calls = await container.faces.list_calls.execute(device_id)
    return DeviceCallListOut(items=[DeviceCallOut.of(c) for c in calls])

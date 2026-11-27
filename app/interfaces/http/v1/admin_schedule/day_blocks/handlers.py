"""Handlers of /v1/admin/day-blocks (admin only)."""

from uuid import UUID

from app.interfaces.http.v1.admin_schedule.day_blocks.schemas import (
    DayBlockBody,
    DayBlockResponse,
)
from app.interfaces.http.v1.admin_schedule.deps import AdminActor, ContainerDep

from fastapi import Response


async def list_day_blocks(
    container: ContainerDep, actor: AdminActor
) -> list[DayBlockResponse]:
    """List every non-lesson block, ordered by start time."""
    blocks = await container.academic.day_blocks.list_blocks.execute()
    return [DayBlockResponse.model_validate(block) for block in blocks]


async def create_day_block(
    body: DayBlockBody, container: ContainerDep, actor: AdminActor
) -> DayBlockResponse:
    """Add a non-lesson block."""
    block = await container.academic.day_blocks.create_block.execute(
        **body.model_dump()
    )
    return DayBlockResponse.model_validate(block)


async def update_day_block(
    block_id: UUID, body: DayBlockBody, container: ContainerDep, actor: AdminActor
) -> DayBlockResponse:
    """Replace every field of a non-lesson block."""
    block = await container.academic.day_blocks.update_block.execute(
        block_id, **body.model_dump()
    )
    return DayBlockResponse.model_validate(block)


async def delete_day_block(
    block_id: UUID, container: ContainerDep, actor: AdminActor
) -> Response:
    """Delete a non-lesson block."""
    await container.academic.day_blocks.delete_block.execute(block_id)
    return Response(status_code=204)

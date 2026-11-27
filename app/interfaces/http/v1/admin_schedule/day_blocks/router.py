"""Router of /v1/admin/day-blocks: lunch, second lunch, breaks, assemblies."""

from app.interfaces.http.v1.admin_schedule.day_blocks.handlers import (
    create_day_block,
    delete_day_block,
    list_day_blocks,
    update_day_block,
)
from app.interfaces.http.v1.admin_schedule.day_blocks.schemas import DayBlockResponse

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/day-blocks", tags=["admin-schedule"])
router.add_api_route(
    "", list_day_blocks, methods=["GET"], response_model=list[DayBlockResponse]
)
router.add_api_route(
    "",
    create_day_block,
    methods=["POST"],
    response_model=DayBlockResponse,
    status_code=201,
)
router.add_api_route(
    "/{block_id}",
    update_day_block,
    methods=["PUT"],
    response_model=DayBlockResponse,
)
router.add_api_route(
    "/{block_id}", delete_day_block, methods=["DELETE"], status_code=204
)

"""Router of /v1/staff/groups."""

from app.interfaces.http.v1.admin_schedule.groups.schemas import (
    GroupDetailResponse,
    GroupItemResponse,
)
from app.interfaces.http.v1.staff_groups.handlers.assign_subgroups import (
    assign_subgroups,
)
from app.interfaces.http.v1.staff_groups.handlers.get_group import get_group
from app.interfaces.http.v1.staff_groups.handlers.list_groups import list_groups

from fastapi import APIRouter

router = APIRouter(prefix="/v1/staff/groups", tags=["staff-groups"])
router.add_api_route(
    "", list_groups, methods=["GET"], response_model=list[GroupItemResponse]
)
router.add_api_route(
    "/{group_id}", get_group, methods=["GET"], response_model=GroupDetailResponse
)
router.add_api_route(
    "/{group_id}/subgroups",
    assign_subgroups,
    methods=["PUT"],
    response_model=GroupDetailResponse,
)

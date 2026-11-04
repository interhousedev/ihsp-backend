"""Router of /v1/admin/groups."""

from app.interfaces.http.v1.admin_schedule.groups.curriculum_schemas import (
    CurriculumResponse,
    CurriculumSyncResponse,
)
from app.interfaces.http.v1.admin_schedule.groups.handlers.assign_subgroups import (
    assign_subgroups,
)
from app.interfaces.http.v1.admin_schedule.groups.handlers.create_group import (
    create_group,
)
from app.interfaces.http.v1.admin_schedule.groups.handlers.export_group_photos import (
    export_group_photos,
)
from app.interfaces.http.v1.admin_schedule.groups.handlers.get_curriculum import (
    get_curriculum,
)
from app.interfaces.http.v1.admin_schedule.groups.handlers.get_group import get_group
from app.interfaces.http.v1.admin_schedule.groups.handlers.list_groups import (
    list_groups,
)
from app.interfaces.http.v1.admin_schedule.groups.handlers.sync_curriculum import (
    sync_curriculum,
)
from app.interfaces.http.v1.admin_schedule.groups.handlers.update_group import (
    update_group,
)
from app.interfaces.http.v1.admin_schedule.groups.schemas import (
    GroupDetailResponse,
    GroupItemResponse,
)

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/v1/admin/groups", tags=["admin-schedule"])
router.add_api_route(
    "", list_groups, methods=["GET"], response_model=list[GroupItemResponse]
)
router.add_api_route(
    "", create_group, methods=["POST"], response_model=GroupItemResponse
)
router.add_api_route(
    "/{group_id}", get_group, methods=["GET"], response_model=GroupDetailResponse
)
router.add_api_route(
    "/{group_id}", update_group, methods=["PATCH"], response_model=GroupDetailResponse
)
router.add_api_route(
    "/{group_id}/photos.zip",
    export_group_photos,
    methods=["GET"],
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "ZIP of the active students' photos, named by full name.",
            "content": {"application/zip": {}},
        }
    },
)
router.add_api_route(
    "/{group_id}/subgroups",
    assign_subgroups,
    methods=["PUT"],
    response_model=GroupDetailResponse,
)
router.add_api_route(
    "/{group_id}/curriculum",
    get_curriculum,
    methods=["GET"],
    response_model=CurriculumResponse | None,
)
router.add_api_route(
    "/{group_id}/curriculum/sync",
    sync_curriculum,
    methods=["POST"],
    response_model=CurriculumSyncResponse,
)

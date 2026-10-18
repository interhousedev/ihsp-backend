"""Routes of the EMIS sync monitor."""

from app.interfaces.http.v1.admin_sync.handlers.list_runs import list_runs
from app.interfaces.http.v1.admin_sync.handlers.list_student_syncs import (
    list_student_syncs,
)
from app.interfaces.http.v1.admin_sync.handlers.resync_materials import (
    resync_materials,
)
from app.interfaces.http.v1.admin_sync.handlers.run_sync import run_sync
from app.interfaces.http.v1.admin_sync.handlers.stop_run import stop_run
from app.interfaces.http.v1.admin_sync.handlers.stop_student_sync import (
    stop_student_sync,
)
from app.interfaces.http.v1.admin_sync.schemas import SyncRunPageResponse
from app.interfaces.http.v1.me_sync.schemas import SyncStatusResponse

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/sync", tags=["admin-sync"])

router.add_api_route(
    "/runs", list_runs, methods=["GET"], response_model=SyncRunPageResponse
)
router.add_api_route("/run", run_sync, methods=["POST"], status_code=202)
router.add_api_route("/materials", resync_materials, methods=["POST"], status_code=202)
router.add_api_route(
    "/student-syncs",
    list_student_syncs,
    methods=["GET"],
    response_model=list[SyncStatusResponse],
)
router.add_api_route("/runs/{run_id}/stop", stop_run, methods=["POST"], status_code=202)
router.add_api_route(
    "/student-syncs/{user_id}/stop",
    stop_student_sync,
    methods=["POST"],
    status_code=202,
)

"""Routes of the EMIS sync monitor."""

from app.interfaces.http.v1.admin_sync.handlers.list_runs import list_runs
from app.interfaces.http.v1.admin_sync.handlers.run_sync import run_sync
from app.interfaces.http.v1.admin_sync.schemas import SyncRunPageResponse

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/sync", tags=["admin-sync"])

router.add_api_route(
    "/runs", list_runs, methods=["GET"], response_model=SyncRunPageResponse
)
router.add_api_route("/run", run_sync, methods=["POST"], status_code=202)

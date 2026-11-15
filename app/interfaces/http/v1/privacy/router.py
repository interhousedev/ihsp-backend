"""Privacy routes: the user's export and erasure, the administrators' queue."""

from app.interfaces.http.v1.privacy.handlers import admin, me
from app.interfaces.http.v1.privacy.schemas import (
    AdminErasureListOut,
    ErasureRequestOut,
    ExportDownloadOut,
    ExportListOut,
    ExportOut,
    MyErasureOut,
)

from fastapi import APIRouter, status

mine = APIRouter(prefix="/v1/me/privacy", tags=["privacy"])
mine.add_api_route(
    "/exports",
    me.request_export,
    methods=["POST"],
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ExportOut,
)
mine.add_api_route(
    "/exports", me.list_exports, methods=["GET"], response_model=ExportListOut
)
mine.add_api_route(
    "/exports/{export_id}/download",
    me.download_export,
    methods=["GET"],
    response_model=ExportDownloadOut,
)
mine.add_api_route(
    "/erasure", me.get_erasure, methods=["GET"], response_model=MyErasureOut
)
mine.add_api_route(
    "/erasure", me.cancel_erasure, methods=["DELETE"], response_model=ErasureRequestOut
)

admin_router = APIRouter(prefix="/v1/admin/privacy", tags=["admin-privacy"])
admin_router.add_api_route(
    "/erasure-requests",
    admin.list_requests,
    methods=["GET"],
    response_model=AdminErasureListOut,
)
admin_router.add_api_route(
    "/erasure-requests/{request_id}/approve",
    admin.approve,
    methods=["POST"],
    response_model=ErasureRequestOut,
)
admin_router.add_api_route(
    "/erasure-requests/{request_id}/reject",
    admin.reject,
    methods=["POST"],
    response_model=ErasureRequestOut,
)

"""Routes under ``/v1/admin/attendance``."""

from app.interfaces.http.v1.admin_attendance.handlers.download_attendance_csv import (
    download_attendance_csv,
)
from app.interfaces.http.v1.admin_attendance.handlers.get_attendance_report import (
    get_attendance_report,
)
from app.interfaces.http.v1.admin_attendance.handlers.get_missing_attendance import (
    get_missing_attendance,
)

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/admin", tags=["admin-attendance"])
router.add_api_route("/attendance", get_attendance_report, methods=["GET"])
router.add_api_route("/attendance/missing", get_missing_attendance, methods=["GET"])
router.add_api_route(
    "/attendance.csv",
    download_attendance_csv,
    methods=["GET"],
    response_class=Response,
)

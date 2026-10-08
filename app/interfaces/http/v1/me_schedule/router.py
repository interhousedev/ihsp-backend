"""Router of /v1/me/profile, /v1/me/timetable and /v1/staff/timetable."""

from app.interfaces.http.v1.admin_schedule.shared_schemas import LessonItemResponse
from app.interfaces.http.v1.me_schedule.handlers.get_profile import get_profile
from app.interfaces.http.v1.me_schedule.handlers.get_staff_timetable import (
    get_staff_timetable,
)
from app.interfaces.http.v1.me_schedule.handlers.get_timetable import get_timetable
from app.interfaces.http.v1.me_schedule.schemas import StudentProfileResponse

from fastapi import APIRouter

router = APIRouter(tags=["schedule"])
router.add_api_route(
    "/v1/me/profile",
    get_profile,
    methods=["GET"],
    response_model=StudentProfileResponse,
)
router.add_api_route(
    "/v1/me/timetable",
    get_timetable,
    methods=["GET"],
    response_model=list[LessonItemResponse],
)
router.add_api_route(
    "/v1/staff/timetable",
    get_staff_timetable,
    methods=["GET"],
    response_model=list[LessonItemResponse],
)

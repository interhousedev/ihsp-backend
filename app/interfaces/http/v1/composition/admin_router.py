"""Routes of the Administration composition endpoints."""

from app.interfaces.http.v1.composition.admin_schemas import (
    AdminDashboardResponse,
    GroupStatsItemResponse,
    Student360Response,
    TeacherProfileResponse,
)
from app.interfaces.http.v1.composition.handlers.get_dashboard import get_dashboard
from app.interfaces.http.v1.composition.handlers.get_group_stats import (
    get_group_stats,
)
from app.interfaces.http.v1.composition.handlers.get_student_360 import (
    get_student_360,
)
from app.interfaces.http.v1.composition.handlers.get_teacher_profile import (
    get_teacher_profile,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin", tags=["composition"])

router.add_api_route(
    "/dashboard",
    get_dashboard,
    methods=["GET"],
    response_model=AdminDashboardResponse,
)
router.add_api_route(
    "/groups/stats",
    get_group_stats,
    methods=["GET"],
    response_model=list[GroupStatsItemResponse],
)
router.add_api_route(
    "/students/{user_id}",
    get_student_360,
    methods=["GET"],
    response_model=Student360Response,
)
router.add_api_route(
    "/teachers/{user_id}/profile",
    get_teacher_profile,
    methods=["GET"],
    response_model=TeacherProfileResponse,
)

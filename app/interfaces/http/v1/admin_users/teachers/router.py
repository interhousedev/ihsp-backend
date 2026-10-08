"""Routes /v1/admin/teachers*."""

from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.admin_users.teachers.handlers.get_teachers import (
    get_teachers,
)
from app.interfaces.http.v1.admin_users.teachers.handlers.patch_teacher import (
    patch_teacher,
)
from app.interfaces.http.v1.admin_users.teachers.handlers.post_deactivate import (
    post_deactivate,
)
from app.interfaces.http.v1.admin_users.teachers.handlers.post_teacher import (
    post_teacher,
)
from app.interfaces.http.v1.admin_users.teachers.schemas import TeacherCreatedResponse
from app.shared.pagination import Page

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/teachers", tags=["admin-teachers"])

router.add_api_route(
    "", get_teachers, methods=["GET"], response_model=Page[AdminUserResponse]
)
router.add_api_route(
    "",
    post_teacher,
    methods=["POST"],
    status_code=201,
    response_model=TeacherCreatedResponse,
)
router.add_api_route(
    "/{id}", patch_teacher, methods=["PATCH"], response_model=AdminUserResponse
)
router.add_api_route(
    "/{id}/deactivate",
    post_deactivate,
    methods=["POST"],
    response_model=AdminUserResponse,
)

"""Router of /v1/admin/lessons."""

from app.interfaces.http.v1.admin_schedule.lessons.handlers.create_lesson import (
    create_lesson,
)
from app.interfaces.http.v1.admin_schedule.lessons.handlers.list_lessons import (
    list_lessons,
)
from app.interfaces.http.v1.admin_schedule.lessons.handlers.update_lesson import (
    update_lesson,
)
from app.interfaces.http.v1.admin_schedule.lessons.schemas import LessonPageResponse
from app.interfaces.http.v1.admin_schedule.shared_schemas import LessonItemResponse

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/lessons", tags=["admin-schedule"])
router.add_api_route(
    "", list_lessons, methods=["GET"], response_model=LessonPageResponse
)
router.add_api_route(
    "", create_lesson, methods=["POST"], response_model=LessonItemResponse
)
router.add_api_route(
    "/{lesson_id}", update_lesson, methods=["PATCH"], response_model=LessonItemResponse
)

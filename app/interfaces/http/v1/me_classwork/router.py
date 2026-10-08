"""Routes under ``/v1/me``: today, lessons, homework, attendance."""

from app.interfaces.http.v1.me_classwork.handlers.get_attendance import get_attendance
from app.interfaces.http.v1.me_classwork.handlers.get_lesson import get_lesson
from app.interfaces.http.v1.me_classwork.handlers.get_today import get_today
from app.interfaces.http.v1.me_classwork.handlers.list_homework import list_homework
from app.interfaces.http.v1.me_classwork.handlers.set_homework_done import (
    set_homework_done,
)
from app.interfaces.http.v1.me_classwork.handlers.set_homework_note import (
    set_homework_note,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/me", tags=["me-classwork"])
router.add_api_route("/today", get_today, methods=["GET"])
router.add_api_route("/lessons/{id}", get_lesson, methods=["GET"])
router.add_api_route("/homework", list_homework, methods=["GET"])
router.add_api_route("/homework/{lesson_id}/done", set_homework_done, methods=["PUT"])
router.add_api_route("/homework/{lesson_id}/note", set_homework_note, methods=["PUT"])
router.add_api_route("/attendance", get_attendance, methods=["GET"])

"""Routes under ``/v1/staff``: today, lessons, journal and attendance reports."""

from app.interfaces.http.v1.staff_classwork.handlers.clear_homework import (
    clear_homework,
)
from app.interfaces.http.v1.staff_classwork.handlers.download_group_attendance_csv import (  # noqa: E501
    download_group_attendance_csv,
)
from app.interfaces.http.v1.staff_classwork.handlers.download_journal_csv import (
    download_journal_csv,
)
from app.interfaces.http.v1.staff_classwork.handlers.get_group_attendance import (
    get_group_attendance,
)
from app.interfaces.http.v1.staff_classwork.handlers.get_journal import get_journal
from app.interfaces.http.v1.staff_classwork.handlers.get_journal_options import (
    get_journal_options,
)
from app.interfaces.http.v1.staff_classwork.handlers.get_lesson import get_lesson
from app.interfaces.http.v1.staff_classwork.handlers.get_today import get_today
from app.interfaces.http.v1.staff_classwork.handlers.list_group_students import (
    list_group_students,
)
from app.interfaces.http.v1.staff_classwork.handlers.set_excuse import set_excuse
from app.interfaces.http.v1.staff_classwork.handlers.set_homework import set_homework
from app.interfaces.http.v1.staff_classwork.handlers.set_topic import set_topic
from app.interfaces.http.v1.staff_classwork.handlers.submit_attendance import (
    submit_attendance,
)
from app.interfaces.http.v1.staff_classwork.handlers.toggle_journal_cell import (
    toggle_journal_cell,
)

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/staff", tags=["staff-classwork"])
router.add_api_route("/today", get_today, methods=["GET"])
router.add_api_route("/lessons/{id}", get_lesson, methods=["GET"])
router.add_api_route("/lessons/{id}/homework", set_homework, methods=["PUT"])
router.add_api_route("/lessons/{id}/homework", clear_homework, methods=["DELETE"])
router.add_api_route("/lessons/{id}/topic", set_topic, methods=["PUT"])
router.add_api_route("/lessons/{id}/attendance", submit_attendance, methods=["PUT"])
router.add_api_route("/lessons/{id}/attendance/excuse", set_excuse, methods=["PUT"])
router.add_api_route("/journal", get_journal, methods=["GET"])
router.add_api_route("/journal/options", get_journal_options, methods=["GET"])
router.add_api_route("/journal/toggle", toggle_journal_cell, methods=["POST"])
router.add_api_route(
    "/journal.csv", download_journal_csv, methods=["GET"], response_class=Response
)
router.add_api_route("/groups/{id}/attendance", get_group_attendance, methods=["GET"])
router.add_api_route(
    "/groups/{id}/attendance.csv",
    download_group_attendance_csv,
    methods=["GET"],
    response_class=Response,
)
router.add_api_route("/groups/{id}/students", list_group_students, methods=["GET"])

"""Routes /v1/me/teachers (+ one teacher, timetable), staff and admin contacts."""

from app.interfaces.http.v1.me_teachers.handlers import (
    get_my_contacts,
    get_my_teacher,
    get_my_teacher_timetable,
    get_my_teachers,
    get_teacher_contacts,
    put_my_contacts,
    put_teacher_contacts,
)
from app.interfaces.http.v1.me_teachers.schemas import (
    MyTeacherResponse,
    TeacherSlotResponse,
)
from app.shared.contracts.identity import TeacherContacts

from fastapi import APIRouter

router = APIRouter(tags=["teachers"])
router.add_api_route(
    "/v1/me/teachers",
    get_my_teachers,
    methods=["GET"],
    response_model=list[MyTeacherResponse],
)
router.add_api_route(
    "/v1/me/teachers/{teacher_id}",
    get_my_teacher,
    methods=["GET"],
    response_model=MyTeacherResponse,
)
router.add_api_route(
    "/v1/me/teachers/{teacher_id}/timetable",
    get_my_teacher_timetable,
    methods=["GET"],
    response_model=list[TeacherSlotResponse],
)
router.add_api_route(
    "/v1/staff/me/contacts",
    get_my_contacts,
    methods=["GET"],
    response_model=TeacherContacts,
)
router.add_api_route(
    "/v1/staff/me/contacts",
    put_my_contacts,
    methods=["PUT"],
    response_model=TeacherContacts,
)
router.add_api_route(
    "/v1/admin/teacher-contacts/{id}",
    get_teacher_contacts,
    methods=["GET"],
    response_model=TeacherContacts,
)
router.add_api_route(
    "/v1/admin/teacher-contacts/{id}",
    put_teacher_contacts,
    methods=["PUT"],
    response_model=TeacherContacts,
)

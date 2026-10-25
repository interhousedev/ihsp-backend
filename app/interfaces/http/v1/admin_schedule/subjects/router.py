"""Router of /v1/admin/subjects."""

from app.interfaces.http.v1.admin_schedule.subjects.handlers.create_subject import (
    create_subject,
)
from app.interfaces.http.v1.admin_schedule.subjects.handlers.emis_pull import (
    emis_pull,
)
from app.interfaces.http.v1.admin_schedule.subjects.handlers.list_subjects import (
    list_subjects,
)
from app.interfaces.http.v1.admin_schedule.subjects.handlers.subject_people import (
    subject_people,
)
from app.interfaces.http.v1.admin_schedule.subjects.handlers.update_subject import (
    update_subject,
)
from app.interfaces.http.v1.admin_schedule.subjects.schemas import (
    SubjectPeopleResponse,
    SubjectResponse,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/subjects", tags=["admin-schedule"])
router.add_api_route(
    "", list_subjects, methods=["GET"], response_model=list[SubjectResponse]
)
router.add_api_route(
    "", create_subject, methods=["POST"], response_model=SubjectResponse
)
router.add_api_route(
    "/{subject_id}", update_subject, methods=["PATCH"], response_model=SubjectResponse
)
router.add_api_route(
    "/{subject_id}/people",
    subject_people,
    methods=["GET"],
    response_model=SubjectPeopleResponse,
)
router.add_api_route(
    "/{subject_id}/emis-pull", emis_pull, methods=["POST"], status_code=202
)

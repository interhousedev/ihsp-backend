"""Router of /v1/staff/subjects/{subject_id}/groups (read-only)."""

from app.interfaces.http.v1.staff_subjects.handlers.get_group import (
    get_group,
    get_subgroup,
)
from app.interfaces.http.v1.staff_subjects.handlers.get_student import (
    get_student,
    get_subgroup_student,
)
from app.interfaces.http.v1.staff_subjects.schemas import (
    TeachingGroupResponse,
    TeachingStudentResponse,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/staff/subjects", tags=["staff-subjects"])
GROUP = "/{subject_id}/groups/{group_id}"
SUBGROUP = GROUP + "/subgroups/{subgroup}"

router.add_api_route(
    GROUP, get_group, methods=["GET"], response_model=TeachingGroupResponse
)
router.add_api_route(
    SUBGROUP, get_subgroup, methods=["GET"], response_model=TeachingGroupResponse
)
router.add_api_route(
    GROUP + "/students/{student_id}",
    get_student,
    methods=["GET"],
    response_model=TeachingStudentResponse,
)
router.add_api_route(
    SUBGROUP + "/students/{student_id}",
    get_subgroup_student,
    methods=["GET"],
    response_model=TeachingStudentResponse,
)

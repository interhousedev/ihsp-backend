"""Routes of the staff portal controls."""

from app.interfaces.http.v1.me_assessments.schemas import (
    StaffAssessmentItem,
    StaffAssessmentListResponse,
)
from app.interfaces.http.v1.staff_assessments.handlers.create_assessment import (
    create_assessment,
)
from app.interfaces.http.v1.staff_assessments.handlers.delete_assessment import (
    delete_assessment,
)
from app.interfaces.http.v1.staff_assessments.handlers.list_assessments import (
    list_assessments,
)
from app.interfaces.http.v1.staff_assessments.handlers.update_assessment import (
    update_assessment,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/staff/assessments", tags=["staff-assessments"])
router.add_api_route(
    "", list_assessments, methods=["GET"], response_model=StaffAssessmentListResponse
)
router.add_api_route(
    "",
    create_assessment,
    methods=["POST"],
    response_model=StaffAssessmentItem,
    status_code=201,
)
router.add_api_route(
    "/{assessment_id}",
    update_assessment,
    methods=["PATCH"],
    response_model=StaffAssessmentItem,
)
router.add_api_route(
    "/{assessment_id}", delete_assessment, methods=["DELETE"], status_code=204
)

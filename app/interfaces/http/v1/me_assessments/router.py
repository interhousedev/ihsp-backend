"""Routes of the student exam calendar."""

from app.interfaces.http.v1.me_assessments.handlers.list_assessments import (
    list_assessments,
)
from app.interfaces.http.v1.me_assessments.handlers.propose_assessment import (
    propose_assessment,
)
from app.interfaces.http.v1.me_assessments.schemas import (
    AssessmentItem,
    AssessmentListResponse,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/me/assessments", tags=["assessments"])
router.add_api_route(
    "", list_assessments, methods=["GET"], response_model=AssessmentListResponse
)
router.add_api_route(
    "",
    propose_assessment,
    methods=["POST"],
    response_model=AssessmentItem,
    status_code=201,
)

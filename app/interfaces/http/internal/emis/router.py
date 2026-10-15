"""Internal EMIS gateway routes (private network, service token)."""

from app.interfaces.http.internal.emis.handlers.get_class_hours import get_class_hours
from app.interfaces.http.internal.emis.handlers.get_curriculum import get_curriculum
from app.interfaces.http.internal.emis.handlers.get_file import get_file
from app.interfaces.http.internal.emis.handlers.get_profile import get_profile
from app.interfaces.http.internal.emis.handlers.get_ratings import get_ratings
from app.interfaces.http.internal.emis.handlers.get_subjects import get_subjects
from app.interfaces.http.internal.emis.handlers.get_timetable import get_timetable
from app.interfaces.http.internal.emis.schemas import (
    EmisClassHourResponse,
    EmisClassResponse,
    EmisCurriculumResponse,
    EmisProfileResponse,
    EmisSubjectRatingsResponse,
    EmisSubjectResponse,
)
from app.interfaces.http.internal.emis.service_auth import require_service_token

from fastapi import APIRouter, Depends

router = APIRouter(
    prefix="/internal/emis",
    tags=["internal-emis"],
    dependencies=[Depends(require_service_token)],
)

router.add_api_route(
    "/{user_id}/profile",
    get_profile,
    methods=["GET"],
    response_model=EmisProfileResponse,
)
router.add_api_route(
    "/{user_id}/subjects",
    get_subjects,
    methods=["GET"],
    response_model=list[EmisSubjectResponse],
)
router.add_api_route(
    "/{user_id}/curriculum",
    get_curriculum,
    methods=["GET"],
    response_model=EmisCurriculumResponse,
)
router.add_api_route(
    "/{user_id}/ratings",
    get_ratings,
    methods=["GET"],
    response_model=EmisSubjectRatingsResponse,
)
router.add_api_route(
    "/{user_id}/class-hours",
    get_class_hours,
    methods=["GET"],
    response_model=list[EmisClassHourResponse],
)
router.add_api_route(
    "/{user_id}/timetable",
    get_timetable,
    methods=["GET"],
    response_model=list[EmisClassResponse],
)
router.add_api_route("/{user_id}/file", get_file, methods=["GET"])

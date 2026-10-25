"""Route of the student's group curriculum."""

from app.interfaces.http.v1.admin_schedule.groups.curriculum_schemas import (
    CurriculumResponse,
)
from app.interfaces.http.v1.me_curriculum.handlers.get_curriculum import get_curriculum

from fastapi import APIRouter

router = APIRouter(prefix="/v1/me", tags=["marks"])

router.add_api_route(
    "/curriculum",
    get_curriculum,
    methods=["GET"],
    response_model=CurriculumResponse | None,
)

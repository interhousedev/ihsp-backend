"""Routes where LMS admins manage the course creators."""

from app.interfaces.http.v1.lms_authoring.creators.handlers.add_creator import (
    add_creator,
)
from app.interfaces.http.v1.lms_authoring.creators.handlers.list_creators import (
    list_creators,
)
from app.interfaces.http.v1.lms_authoring.creators.handlers.remove_creator import (
    remove_creator,
)
from app.interfaces.http.v1.lms_authoring.creators.schemas import (
    CourseCreatorResponse,
)
from app.shared.pagination import Page

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/staff/lms/creators", tags=["lms-authoring"])
router.add_api_route(
    "", list_creators, methods=["GET"], response_model=Page[CourseCreatorResponse]
)
router.add_api_route(
    "/{user_id}",
    add_creator,
    methods=["PUT"],
    response_model=CourseCreatorResponse,
)
router.add_api_route(
    "/{user_id}",
    remove_creator,
    methods=["DELETE"],
    status_code=204,
    response_class=Response,
)

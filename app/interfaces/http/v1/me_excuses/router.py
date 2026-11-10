"""Routes of the student's excuses (`/v1/me/excuse*`)."""

from app.interfaces.http.v1.me_excuses import handlers
from app.interfaces.http.v1.me_excuses.schemas import (
    ExcuseListOut,
    ExcuseOut,
    ExcuseTemplateListOut,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/me", tags=["excuses"])

router.add_api_route(
    "/excuse-templates",
    handlers.list_templates,
    methods=["GET"],
    response_model=ExcuseTemplateListOut,
)
router.add_api_route(
    "/excuses", handlers.list_mine, methods=["GET"], response_model=ExcuseListOut
)
router.add_api_route(
    "/excuses",
    handlers.request_excuse,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=ExcuseOut,
)
router.add_api_route(
    "/excuses/{excuse_id}",
    handlers.get_mine,
    methods=["GET"],
    response_model=ExcuseOut,
)
router.add_api_route(
    "/excuses/{excuse_id}/messages",
    handlers.post_message,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=ExcuseOut,
)
router.add_api_route(
    "/excuses/{excuse_id}/cancel",
    handlers.cancel,
    methods=["POST"],
    response_model=ExcuseOut,
)

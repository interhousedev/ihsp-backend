"""Routes of Administration's excuses (`/v1/admin/excuses*`)."""

from app.interfaces.http.v1.admin_excuses import handlers
from app.interfaces.http.v1.me_excuses.schemas import ExcuseListOut, ExcuseOut

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/admin/excuses", tags=["admin-excuses"])

router.add_api_route(
    "", handlers.list_excuses, methods=["GET"], response_model=ExcuseListOut
)
router.add_api_route(
    "/{excuse_id}", handlers.get_excuse, methods=["GET"], response_model=ExcuseOut
)
router.add_api_route(
    "/{excuse_id}/approve", handlers.approve, methods=["POST"], response_model=ExcuseOut
)
router.add_api_route(
    "/{excuse_id}/reject", handlers.reject, methods=["POST"], response_model=ExcuseOut
)
router.add_api_route(
    "/{excuse_id}/messages",
    handlers.post_message,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=ExcuseOut,
)

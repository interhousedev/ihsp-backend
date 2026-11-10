"""Routes of the curator's excuses (`/v1/staff/excuses*`)."""

from app.interfaces.http.v1.me_excuses.schemas import ExcuseListOut, ExcuseOut
from app.interfaces.http.v1.staff_excuses import handlers

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/staff/excuses", tags=["staff-excuses"])

router.add_api_route(
    "", handlers.list_excuses, methods=["GET"], response_model=ExcuseListOut
)
router.add_api_route(
    "",
    handlers.create_exclusion,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=ExcuseOut,
)
router.add_api_route(
    "/{excuse_id}", handlers.get_excuse, methods=["GET"], response_model=ExcuseOut
)
router.add_api_route(
    "/{excuse_id}", handlers.end_excuse, methods=["PATCH"], response_model=ExcuseOut
)
for name in ("approve", "reject", "revoke"):
    router.add_api_route(
        f"/{{excuse_id}}/{name}",
        getattr(handlers, name),
        methods=["POST"],
        response_model=ExcuseOut,
    )
router.add_api_route(
    "/{excuse_id}/messages",
    handlers.post_message,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=ExcuseOut,
)

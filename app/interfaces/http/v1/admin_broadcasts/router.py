"""Routes of broadcasts for Administration (ADM-11)."""

from app.interfaces.http.v1.admin_broadcasts.handlers.audience_count import (
    audience_count,
)
from app.interfaces.http.v1.admin_broadcasts.handlers.cancel_broadcast import (
    cancel_broadcast,
)
from app.interfaces.http.v1.admin_broadcasts.handlers.create_broadcast import (
    create_broadcast,
)
from app.interfaces.http.v1.admin_broadcasts.handlers.get_broadcast import (
    get_broadcast,
)
from app.interfaces.http.v1.admin_broadcasts.handlers.list_broadcasts import (
    list_broadcasts,
)
from app.interfaces.http.v1.admin_broadcasts.handlers.preview_broadcast import (
    preview_broadcast,
)
from app.interfaces.http.v1.admin_broadcasts.handlers.send_broadcast import (
    send_broadcast,
)
from app.interfaces.http.v1.admin_broadcasts.handlers.update_broadcast import (
    update_broadcast,
)
from app.interfaces.http.v1.admin_broadcasts.schemas import (
    AudienceCountResponse,
    BroadcastResponse,
)
from app.shared.pagination import Page

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/admin/broadcasts", tags=["admin-broadcasts"])

router.add_api_route(
    "", list_broadcasts, methods=["GET"], response_model=Page[BroadcastResponse]
)
router.add_api_route(
    "", create_broadcast, methods=["POST"], response_model=BroadcastResponse
)
router.add_api_route(
    "/audience-count",
    audience_count,
    methods=["POST"],
    response_model=AudienceCountResponse,
)
router.add_api_route(
    "/{broadcast_id}",
    get_broadcast,
    methods=["GET"],
    response_model=BroadcastResponse,
)
router.add_api_route(
    "/{broadcast_id}",
    update_broadcast,
    methods=["PATCH"],
    response_model=BroadcastResponse,
)
router.add_api_route(
    "/{broadcast_id}/preview",
    preview_broadcast,
    methods=["POST"],
    status_code=204,
    response_class=Response,
)
router.add_api_route(
    "/{broadcast_id}/send",
    send_broadcast,
    methods=["POST"],
    response_model=BroadcastResponse,
)
router.add_api_route(
    "/{broadcast_id}/cancel",
    cancel_broadcast,
    methods=["POST"],
    response_model=BroadcastResponse,
)

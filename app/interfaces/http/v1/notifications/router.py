"""Routes of the notification center."""

from app.interfaces.http.v1.notifications.handlers.list_notifications import (
    list_notifications,
)
from app.interfaces.http.v1.notifications.handlers.mark_all_read import mark_all_read
from app.interfaces.http.v1.notifications.handlers.mark_read import mark_read
from app.interfaces.http.v1.notifications.handlers.unread_count import unread_count
from app.interfaces.http.v1.notifications.schemas import (
    NotificationItemResponse,
    UnreadCountResponse,
)
from app.shared.pagination import Page

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])

router.add_api_route(
    "",
    list_notifications,
    methods=["GET"],
    response_model=Page[NotificationItemResponse],
)
router.add_api_route(
    "/unread-count",
    unread_count,
    methods=["GET"],
    response_model=UnreadCountResponse,
)
router.add_api_route(
    "/read-all",
    mark_all_read,
    methods=["POST"],
    status_code=204,
    response_class=Response,
)
router.add_api_route(
    "/{notification_id}/read",
    mark_read,
    methods=["POST"],
    status_code=204,
    response_class=Response,
)

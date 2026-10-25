"""Routes of Web Push."""

from app.interfaces.http.v1.push.handlers.get_config import get_config
from app.interfaces.http.v1.push.handlers.subscribe import subscribe
from app.interfaces.http.v1.push.handlers.unsubscribe import unsubscribe
from app.interfaces.http.v1.push.schemas import (
    PushConfigResponse,
    PushSubscriptionResponse,
)

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1", tags=["push"])

router.add_api_route(
    "/push/config", get_config, methods=["GET"], response_model=PushConfigResponse
)
router.add_api_route(
    "/me/push-subscriptions",
    subscribe,
    methods=["POST"],
    status_code=201,
    response_model=PushSubscriptionResponse,
)
router.add_api_route(
    "/me/push-subscriptions",
    unsubscribe,
    methods=["DELETE"],
    status_code=204,
    response_class=Response,
)

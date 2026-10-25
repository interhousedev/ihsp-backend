"""Routes of staff account activation."""

from app.interfaces.http.v1.id.activation.handlers.get_activation import get_activation
from app.interfaces.http.v1.id.activation.handlers.post_activation import (
    post_activation,
)
from app.interfaces.http.v1.id.activation.handlers.post_activation_email import (
    post_activation_email,
)
from app.interfaces.http.v1.id.activation.schemas import (
    ActivationInfoResponse,
    RedirectResponseBody,
)

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/id/activation", tags=["id-activation"])

router.add_api_route(
    "/{token}", get_activation, methods=["GET"], response_model=ActivationInfoResponse
)
router.add_api_route(
    "/{token}/email",
    post_activation_email,
    methods=["POST"],
    status_code=202,
    response_class=Response,
)
router.add_api_route(
    "/{token}",
    post_activation,
    methods=["POST"],
    response_model=RedirectResponseBody,
)

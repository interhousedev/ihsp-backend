"""Routes /v1/admin/oauth-clients*."""

from app.interfaces.http.v1.admin_users.oauth_clients.handlers.get_clients import (
    get_clients,
)
from app.interfaces.http.v1.admin_users.oauth_clients.handlers.post_verify import (
    post_verify,
)
from app.interfaces.http.v1.admin_users.oauth_clients.schemas import OAuthClientResponse

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/oauth-clients", tags=["admin-oauth-clients"])

router.add_api_route(
    "", get_clients, methods=["GET"], response_model=list[OAuthClientResponse]
)
router.add_api_route(
    "/{client_id}/verify",
    post_verify,
    methods=["POST"],
    response_model=OAuthClientResponse,
)

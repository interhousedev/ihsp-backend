"""Hydra's login, consent and logout URLs: browser redirects, not JSON.

They are not part of the JSON API, so they stay out of the OpenAPI document.
"""

from app.interfaces.http.v1.oauth.flow.handlers.get_flow_consent import (
    get_flow_consent,
)
from app.interfaces.http.v1.oauth.flow.handlers.get_flow_login import get_flow_login
from app.interfaces.http.v1.oauth.flow.handlers.get_flow_logout import (
    get_flow_logout,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/oauth/flow", tags=["oauth"])

router.add_api_route("/login", get_flow_login, methods=["GET"], include_in_schema=False)
router.add_api_route(
    "/consent", get_flow_consent, methods=["GET"], include_in_schema=False
)
router.add_api_route(
    "/logout", get_flow_logout, methods=["GET"], include_in_schema=False
)

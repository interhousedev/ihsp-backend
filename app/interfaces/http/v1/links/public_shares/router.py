"""Public routes of shares and reports (share origin CORS, no credentials)."""

from app.interfaces.http.v1.links.public_shares.handlers.get_public_share import (
    get_public_share,
)
from app.interfaces.http.v1.links.public_shares.handlers.get_public_visualization import (  # noqa: E501
    get_public_visualization,
)
from app.interfaces.http.v1.links.public_shares.handlers.report_link import report_link
from app.interfaces.http.v1.links.public_shares.schemas import (
    PublicShare,
    PublicVisualization,
)

from fastapi import APIRouter

router = APIRouter(tags=["public"])
router.add_api_route(
    "/v1/public/shares/{slug}",
    get_public_share,
    methods=["GET"],
    response_model=PublicShare,
)
router.add_api_route(
    "/v1/public/visualizations/{slug}",
    get_public_visualization,
    methods=["GET"],
    response_model=PublicVisualization,
)
router.add_api_route(
    "/v1/public/reports", report_link, methods=["POST"], status_code=202
)

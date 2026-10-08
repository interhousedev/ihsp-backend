"""Routes of shares."""

from app.interfaces.http.v1.links.schemas import LinkItem
from app.interfaces.http.v1.links.shares.handlers.create_share import create_share

from fastapi import APIRouter

router = APIRouter(tags=["links"])
router.add_api_route(
    "/v1/shares", create_share, methods=["POST"], response_model=LinkItem
)

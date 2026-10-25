"""Routes of short links."""

from app.interfaces.http.v1.links.links.handlers.create_link import create_link
from app.interfaces.http.v1.links.links.handlers.delete_link import delete_link
from app.interfaces.http.v1.links.links.handlers.list_my_links import list_my_links
from app.interfaces.http.v1.links.links.handlers.revoke_link import revoke_link
from app.interfaces.http.v1.links.links.schemas import LinkPageResponse
from app.interfaces.http.v1.links.schemas import LinkItem

from fastapi import APIRouter

router = APIRouter(tags=["links"])
router.add_api_route(
    "/v1/links", create_link, methods=["POST"], response_model=LinkItem
)
router.add_api_route(
    "/v1/me/links", list_my_links, methods=["GET"], response_model=LinkPageResponse
)
router.add_api_route(
    "/v1/links/{link_id}", delete_link, methods=["DELETE"], status_code=204
)
router.add_api_route(
    "/v1/links/{link_id}/revoke",
    revoke_link,
    methods=["POST"],
    response_model=LinkItem,
)

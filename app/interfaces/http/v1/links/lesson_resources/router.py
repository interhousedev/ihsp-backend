"""Routes of lesson resources."""

from app.interfaces.http.v1.links.lesson_resources.handlers.add_resources import (
    add_resources,
)
from app.interfaces.http.v1.links.lesson_resources.handlers.delete_resource import (
    delete_resource,
)
from app.interfaces.http.v1.links.lesson_resources.handlers.hide_resource import (
    hide_resource,
)
from app.interfaces.http.v1.links.lesson_resources.handlers.list_resources import (
    list_resources,
)
from app.interfaces.http.v1.links.schemas import ResourceItem

from fastapi import APIRouter

router = APIRouter(tags=["links"])
PATH = "/v1/lessons/{lesson_id}/resources"
router.add_api_route(
    PATH, list_resources, methods=["GET"], response_model=list[ResourceItem]
)
router.add_api_route(
    PATH, add_resources, methods=["POST"], response_model=list[ResourceItem]
)
router.add_api_route(
    PATH + "/{link_id}", delete_resource, methods=["DELETE"], status_code=204
)
router.add_api_route(
    PATH + "/{link_id}/hide",
    hide_resource,
    methods=["POST"],
    response_model=ResourceItem,
)

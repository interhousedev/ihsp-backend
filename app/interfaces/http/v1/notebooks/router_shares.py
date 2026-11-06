"""Routes of sharing notebooks; registered before the routes of one notebook."""

from app.interfaces.http.v1.notebooks.handlers import notebook_shares as handlers

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/notebooks", tags=["notebooks"])
_NO_CONTENT = status.HTTP_204_NO_CONTENT

router.add_api_route("/shared", handlers.list_shared, methods=["GET"])
router.add_api_route("/share-recipients", handlers.search_recipients, methods=["GET"])
router.add_api_route("/shares/join", handlers.join_share, methods=["POST"])
router.add_api_route("/{notebook_id}/shares", handlers.get_shares, methods=["GET"])
router.add_api_route(
    "/{notebook_id}/shares/link", handlers.create_share_link, methods=["POST"]
)
router.add_api_route(
    "/{notebook_id}/shares/link",
    handlers.delete_share_link,
    methods=["DELETE"],
    status_code=_NO_CONTENT,
)
router.add_api_route(
    "/{notebook_id}/shares/{user_id}",
    handlers.add_share_person,
    methods=["PUT"],
    status_code=_NO_CONTENT,
)
router.add_api_route(
    "/{notebook_id}/shares/{user_id}",
    handlers.remove_share_person,
    methods=["DELETE"],
    status_code=_NO_CONTENT,
)
router.add_api_route(
    "/{notebook_id}/membership",
    handlers.leave_shared,
    methods=["DELETE"],
    status_code=_NO_CONTENT,
)
router.add_api_route(
    "/{notebook_id}/linked-sets", handlers.list_linked_sets, methods=["GET"]
)
router.add_api_route(
    "/{notebook_id}/linked-sets",
    handlers.attach_linked_set,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/{notebook_id}/linked-sets/{linked_id}",
    handlers.detach_linked_set,
    methods=["DELETE"],
    status_code=_NO_CONTENT,
)

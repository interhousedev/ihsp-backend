"""Routes of collections: public shelves and the librarian's editor."""

from app.interfaces.http.v1.library.taxonomy.handlers import (
    create_collection,
    delete_collection,
    get_collection,
    list_collections,
    list_manage_collections,
    update_collection,
)

from fastapi import APIRouter, status

router = APIRouter(tags=["library"])

router.add_api_route(
    "/v1/library/collections", list_collections.list_collections, methods=["GET"]
)
router.add_api_route(
    "/v1/library/collections/{collection_id}",
    get_collection.get_collection,
    methods=["GET"],
)
router.add_api_route(
    "/v1/manage/library/collections",
    list_manage_collections.list_manage_collections,
    methods=["GET"],
)
router.add_api_route(
    "/v1/manage/library/collections",
    create_collection.create_collection,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/v1/manage/library/collections/{collection_id}",
    update_collection.update_collection,
    methods=["PATCH"],
)
router.add_api_route(
    "/v1/manage/library/collections/{collection_id}",
    delete_collection.delete_collection,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)

"""Routes of the catalogue: browse, item page, file URL, text, subjects."""

from app.interfaces.http.v1.library.catalogue.handlers import (
    get_file_url,
    get_item,
    get_item_text,
    list_items,
    list_subjects,
    search_labels,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/library", tags=["library"])

router.add_api_route("/subjects", list_subjects.list_subjects, methods=["GET"])
router.add_api_route("/authors", search_labels.search_authors, methods=["GET"])
router.add_api_route("/tags", search_labels.search_tags, methods=["GET"])
router.add_api_route("/items", list_items.list_items, methods=["GET"])
router.add_api_route(
    "/items/{item_id}/files/{file_id}/url", get_file_url.get_file_url, methods=["GET"]
)
router.add_api_route(
    "/items/{item_id}/text", get_item_text.get_item_text, methods=["GET"]
)
router.add_api_route("/items/{id_or_slug}", get_item.get_item, methods=["GET"])

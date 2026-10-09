"""Routes of the UniLibrary records: search, record, pin, taxonomies (signed in)."""

from app.interfaces.http.v1.library.external.handlers import (
    get_unilibrary_record,
    get_unilibrary_taxonomies,
    pin_unilibrary_record,
    search_unilibrary,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/library/external/unilibrary", tags=["library"])

# Fixed paths before `/{external_id}`, or "search" would be read as a record id.
router.add_api_route("/search", search_unilibrary.search_unilibrary, methods=["GET"])
router.add_api_route(
    "/taxonomies", get_unilibrary_taxonomies.get_unilibrary_taxonomies, methods=["GET"]
)
router.add_api_route(
    "/{external_id}", get_unilibrary_record.get_unilibrary_record, methods=["GET"]
)
router.add_api_route(
    "/{external_id}/item",
    pin_unilibrary_record.pin_unilibrary_record,
    methods=["POST"],
)

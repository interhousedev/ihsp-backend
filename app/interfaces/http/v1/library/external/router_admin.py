"""Administration of UniLibrary: switches, feeds, field map, status."""

from app.interfaces.http.v1.library.external.handlers import (
    create_unilibrary_feed,
    delete_unilibrary_feed,
    get_unilibrary_field_map,
    get_unilibrary_settings,
    get_unilibrary_status,
    list_unilibrary_feeds,
    put_unilibrary_field_map,
    put_unilibrary_settings,
    run_unilibrary_feed_action,
    update_unilibrary_feed,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/admin/library/unilibrary", tags=["library-admin"])

router.add_api_route(
    "/settings", get_unilibrary_settings.get_unilibrary_settings, methods=["GET"]
)
router.add_api_route(
    "/settings", put_unilibrary_settings.put_unilibrary_settings, methods=["PUT"]
)
router.add_api_route(
    "/feeds", list_unilibrary_feeds.list_unilibrary_feeds, methods=["GET"]
)
router.add_api_route(
    "/feeds",
    create_unilibrary_feed.create_unilibrary_feed,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/feeds/{feed_id}", update_unilibrary_feed.update_unilibrary_feed, methods=["PATCH"]
)
router.add_api_route(
    "/feeds/{feed_id}",
    delete_unilibrary_feed.delete_unilibrary_feed,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/feeds/{feed_id}/{action}",
    run_unilibrary_feed_action.run_unilibrary_feed_action,
    methods=["POST"],
)
router.add_api_route(
    "/field-map", get_unilibrary_field_map.get_unilibrary_field_map, methods=["GET"]
)
router.add_api_route(
    "/field-map", put_unilibrary_field_map.put_unilibrary_field_map, methods=["PUT"]
)
router.add_api_route(
    "/status", get_unilibrary_status.get_unilibrary_status, methods=["GET"]
)

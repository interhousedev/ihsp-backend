"""Routes of reading lists, the groups they can name and the statistics."""

from app.interfaces.http.v1.library.taxonomy.handlers import (
    create_reading_list,
    delete_reading_list,
    get_library_stats,
    get_reading_list,
    list_my_groups,
    list_reading_lists,
    replace_list_entries,
    update_reading_list,
)

from fastapi import APIRouter, status

router = APIRouter(tags=["library"])

router.add_api_route(
    "/v1/library/reading-lists", list_reading_lists.list_reading_lists, methods=["GET"]
)
router.add_api_route(
    "/v1/library/reading-lists",
    create_reading_list.create_reading_list,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/v1/library/reading-lists/{list_id}",
    get_reading_list.get_reading_list,
    methods=["GET"],
)
router.add_api_route(
    "/v1/library/reading-lists/{list_id}",
    update_reading_list.update_reading_list,
    methods=["PATCH"],
)
router.add_api_route(
    "/v1/library/reading-lists/{list_id}",
    delete_reading_list.delete_reading_list,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/v1/library/reading-lists/{list_id}/items",
    replace_list_entries.replace_list_entries,
    methods=["PUT"],
)
router.add_api_route(
    "/v1/library/my-groups", list_my_groups.list_my_groups, methods=["GET"]
)
router.add_api_route(
    "/v1/manage/library/stats", get_library_stats.get_library_stats, methods=["GET"]
)

"""Routes of the librarian's queue, decisions, reports and suggestions."""

from app.interfaces.http.v1.library.materials.handlers import (
    approve_suggestion,
    decide_suggestion,
    get_suggestion,
    list_queue,
    resolve_report,
    review_item,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/manage/library", tags=["library-manage"])

router.add_api_route("/queue", list_queue.list_queue, methods=["GET"])
router.add_api_route(
    "/items/{item_id}/{action}", review_item.review_item, methods=["POST"]
)
router.add_api_route(
    "/reports/{report_id}/resolve",
    resolve_report.resolve_report,
    methods=["POST"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/suggestions/{suggestion_id}/approve",
    approve_suggestion.approve_suggestion,
    methods=["POST"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/suggestions/{suggestion_id}/{decision}",
    decide_suggestion.decide_suggestion,
    methods=["POST"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/suggestions/{suggestion_id}", get_suggestion.get_suggestion, methods=["GET"]
)

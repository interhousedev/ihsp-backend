"""Routes of the topic labels of a notebook's sources (spec 3.4)."""

from app.interfaces.http.v1.notebooks.handlers import (
    create_label,
    delete_label,
    list_labels,
    set_source_labels,
    start_labeling,
    update_label,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/notebooks", tags=["notebooks"])

router.add_api_route("/{notebook_id}/labels", list_labels.list_labels, methods=["GET"])
router.add_api_route(
    "/{notebook_id}/labels",
    create_label.create_label,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
# Before `/labels/{label_id}`, so that "auto" is never read as a label id.
router.add_api_route(
    "/{notebook_id}/labels/auto",
    start_labeling.start_labeling,
    methods=["POST"],
    status_code=status.HTTP_202_ACCEPTED,
)
router.add_api_route(
    "/{notebook_id}/labels/{label_id}", update_label.update_label, methods=["PATCH"]
)
router.add_api_route(
    "/{notebook_id}/labels/{label_id}",
    delete_label.delete_label,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/{notebook_id}/sources/{source_id}/labels",
    set_source_labels.set_source_labels,
    methods=["PUT"],
)

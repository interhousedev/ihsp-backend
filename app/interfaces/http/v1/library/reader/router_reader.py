"""Routes of My library: shelf, progress, annotations (all private to the caller)."""

from app.interfaces.http.v1.library.reader.handlers import (
    create_annotation,
    delete_annotation,
    export_annotations,
    get_me_library,
    list_annotations,
    list_shelf,
    put_shelf_entry,
    remove_shelf_entry,
    save_progress,
    sync_annotations,
    update_annotation,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/me/library", tags=["library"])

router.add_api_route("", get_me_library.get_me_library, methods=["GET"])
router.add_api_route("/shelf", list_shelf.list_shelf, methods=["GET"])
router.add_api_route(
    "/shelf/{item_id}", put_shelf_entry.put_shelf_entry, methods=["PUT"]
)
router.add_api_route(
    "/shelf/{item_id}",
    remove_shelf_entry.remove_shelf_entry,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/progress/{item_id}",
    save_progress.save_progress,
    methods=["PUT"],
    status_code=status.HTTP_204_NO_CONTENT,
)
# Fixed paths before `/{annotation_id}`.
router.add_api_route(
    "/annotations/export", export_annotations.export_annotations, methods=["GET"]
)
router.add_api_route(
    "/annotations/sync", sync_annotations.sync_annotations, methods=["POST"]
)
router.add_api_route("/annotations", list_annotations.list_annotations, methods=["GET"])
router.add_api_route(
    "/annotations",
    create_annotation.create_annotation,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/annotations/{annotation_id}",
    update_annotation.update_annotation,
    methods=["PATCH"],
)
router.add_api_route(
    "/annotations/{annotation_id}",
    delete_annotation.delete_annotation,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)

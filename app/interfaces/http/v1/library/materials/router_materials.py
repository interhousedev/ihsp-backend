"""Routes of uploading materials, reporting and suggesting."""

from app.interfaces.http.v1.library.materials.handlers import (
    attach_material_files,
    create_material,
    create_material_version,
    create_suggestion,
    list_my_uploads,
    report_item,
    submit_material,
    update_material,
    withdraw_material,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1", tags=["library-materials"])

router.add_api_route(
    "/library/materials",
    create_material.create_material,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/library/materials/{item_id}/files",
    attach_material_files.attach_material_files,
    methods=["POST"],
)
router.add_api_route(
    "/library/materials/{item_id}/submit",
    submit_material.submit_material,
    methods=["POST"],
    status_code=status.HTTP_202_ACCEPTED,
)
router.add_api_route(
    "/library/materials/{item_id}/versions",
    create_material_version.create_material_version,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/library/materials/{item_id}",
    update_material.update_material,
    methods=["PATCH"],
)
router.add_api_route(
    "/library/materials/{item_id}",
    withdraw_material.withdraw_material,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/me/library/uploads", list_my_uploads.list_my_uploads, methods=["GET"]
)
router.add_api_route(
    "/library/suggestions",
    create_suggestion.create_suggestion,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)
router.add_api_route(
    "/library/items/{item_id}/report",
    report_item.report_item,
    methods=["POST"],
    status_code=status.HTTP_204_NO_CONTENT,
)

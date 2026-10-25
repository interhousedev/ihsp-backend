"""Routes of Administration's sanctions."""

from app.interfaces.http.v1.library.materials.handlers import sanctions

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/admin/library", tags=["library-admin"])

router.add_api_route("/sanctions", sanctions.list_sanctions, methods=["GET"])
router.add_api_route(
    "/sanctions",
    sanctions.create_sanction,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
)

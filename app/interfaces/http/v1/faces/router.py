"""Routes of face recognition."""

from app.interfaces.http.v1.faces.handlers import (
    devices,
    identify,
    me_face,
    staff_face,
)
from app.interfaces.http.v1.faces.schemas import (
    DeviceCallListOut,
    DeviceCreatedOut,
    DeviceListOut,
    DeviceOut,
    FaceOut,
    IdentifyOut,
)

from fastapi import APIRouter, status

router = APIRouter(tags=["faces"])

router.add_api_route(
    "/v1/me/face", me_face.get_my_face, methods=["GET"], response_model=FaceOut
)
router.add_api_route(
    "/v1/me/face", me_face.put_my_face, methods=["PUT"], response_model=FaceOut
)
router.add_api_route(
    "/v1/me/face",
    me_face.delete_my_face,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/v1/staff/students/{student_id}/face",
    staff_face.put_student_face,
    methods=["PUT"],
    response_model=FaceOut,
)
router.add_api_route(
    "/v1/staff/students/{student_id}/face",
    staff_face.delete_student_face,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
)
router.add_api_route(
    "/v1/admin/devices",
    devices.list_devices,
    methods=["GET"],
    response_model=DeviceListOut,
)
router.add_api_route(
    "/v1/admin/devices",
    devices.create_device,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=DeviceCreatedOut,
)
router.add_api_route(
    "/v1/admin/devices/{device_id}/revoke",
    devices.revoke_device,
    methods=["POST"],
    response_model=DeviceOut,
)
router.add_api_route(
    "/v1/admin/devices/{device_id}/calls",
    devices.list_device_calls,
    methods=["GET"],
    response_model=DeviceCallListOut,
)
router.add_api_route(
    "/v1/device/identify",
    identify.identify,
    methods=["POST"],
    response_model=IdentifyOut,
)

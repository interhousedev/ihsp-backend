"""POST /v1/device/identify (an entrance device, not a user)."""

from typing import Annotated

from app.interfaces.http.v1.faces.deps import ContainerDep
from app.interfaces.http.v1.faces.handlers.upload import read_image
from app.interfaces.http.v1.faces.schemas import IdentifyOut
from app.modules.faces.domain.errors import DeviceUnauthorizedError
from app.modules.faces.domain.models import Direction

from fastapi import File, Form, Header, UploadFile

BEARER = "bearer "


def device_token(authorization: str | None) -> str:
    """Return the token of `Authorization: Bearer ihsp_dev_...`."""
    if authorization is None or not authorization.lower().startswith(BEARER):
        raise DeviceUnauthorizedError()
    return authorization[len(BEARER) :].strip()


async def identify(
    file: Annotated[UploadFile, File()],
    direction: Annotated[Direction, Form()],
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
) -> IdentifyOut:
    """Recognise the student on the photo and record the passage."""
    token = device_token(authorization)
    data = await read_image(file)
    result = await container.faces.identify.execute(token, direction, data)
    return IdentifyOut.of(result)

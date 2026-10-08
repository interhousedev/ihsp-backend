"""POST /v1/id/register/emis: check EMIS credentials, return the profile."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.v1.id_registration.locale import request_locale
from app.interfaces.http.v1.id_registration.schemas import (
    RegistrationStartResponse,
    StartRegistrationBody,
)

from fastapi import Depends, Request


async def register_emis(
    body: StartRegistrationBody,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> RegistrationStartResponse:
    """Start a registration (ID-1)."""
    started = await container.identity.emis.register_start.execute(
        emis_login=body.emis_login,
        emis_password=body.emis_password.get_secret_value(),
        ip=ip,
        locale=request_locale(request),
    )
    return RegistrationStartResponse.from_result(started)

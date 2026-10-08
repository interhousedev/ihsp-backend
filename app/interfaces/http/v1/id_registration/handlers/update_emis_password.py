"""POST /v1/id/me/emis-password: replace the stored EMIS password."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.id_registration.schemas import (
    EmisPasswordResponse,
    UpdateEmisPasswordBody,
)
from app.shared.actor import Actor, Role

from fastapi import Depends


async def update_emis_password(
    body: UpdateEmisPasswordBody,
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
) -> EmisPasswordResponse:
    """Check the new password against EMIS, then store it (ID-8)."""
    emis_status = await container.identity.emis.update_emis_password.execute(
        actor, emis_password=body.emis_password.get_secret_value()
    )
    return EmisPasswordResponse(emis_status=emis_status)

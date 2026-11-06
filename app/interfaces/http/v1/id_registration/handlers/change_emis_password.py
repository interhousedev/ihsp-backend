"""POST /v1/id/me/emis-password/change: change the password in EMIS itself."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.id_registration.schemas import ChangeEmisPasswordBody
from app.shared.actor import Actor, Role

from fastapi import Depends, Response


async def change_emis_password(
    body: ChangeEmisPasswordBody,
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Check the second factor and the current EMIS password, then change it."""
    await container.identity.emis.change_emis_password.execute(actor, body.to_command())
    return Response(status_code=204)

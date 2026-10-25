"""POST /v1/id/reclaim/emis: prove ownership with EMIS credentials."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.v1.id_registration.schemas import (
    StartReclaimBody,
    StartReclaimResponse,
)

from fastapi import Depends


async def reclaim_emis(
    body: StartReclaimBody,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> StartReclaimResponse:
    """Find the account linked to the EMIS profile (ID-28)."""
    started = await container.identity.emis.reclaim_start.execute(
        emis_login=body.emis_login,
        emis_password=body.emis_password.get_secret_value(),
        ip=ip,
    )
    return StartReclaimResponse(
        reclaim_token=started.reclaim_token, login=started.login
    )

"""Public login cue picker: groups, opaque cue ids and the cue registration start."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_client_ip, get_container
from app.interfaces.http.v1.id_registration.locale import request_locale
from app.interfaces.http.v1.id_registration.schemas import (
    CueGroupResponse,
    CueOptionResponse,
    RegistrationStartResponse,
    StartCueRegistrationBody,
)

from fastapi import Depends, Request


async def list_cue_groups(
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> list[CueGroupResponse]:
    """Groups that still have unclaimed login cues (rate limited per IP)."""
    groups = await container.identity.emis.login_cues.groups_with_cues(ip)
    return [CueGroupResponse(group_id=g.group_id, name=g.name) for g in groups]


async def list_group_cues(
    group_id: UUID,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> list[CueOptionResponse]:
    """Unclaimed cues of a group: opaque id and name only, never the EMIS login."""
    options = await container.identity.emis.login_cues.cues_of_group(group_id, ip)
    return [
        CueOptionResponse(cue_id=o.cue_id, display_name=o.display_name) for o in options
    ]


async def start_cue_registration(
    body: StartCueRegistrationBody,
    request: Request,
    container: Annotated[Container, Depends(get_container)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> RegistrationStartResponse:
    """Start a registration with the EMIS login behind the chosen cue."""
    started = await container.identity.emis.login_cues.start_registration(
        cue_id=body.cue_id,
        emis_password=body.emis_password.get_secret_value(),
        ip=ip,
        locale=request_locale(request),
    )
    return RegistrationStartResponse.from_result(started)

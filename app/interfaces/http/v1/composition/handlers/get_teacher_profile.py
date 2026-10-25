"""GET /v1/admin/teachers/{user_id}/profile."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.dependencies import get_client_ip, require_roles
from app.interfaces.http.v1.composition.dependencies import get_composition
from app.interfaces.http.v1.composition.ports import JsonObject
from app.interfaces.http.v1.composition.services import Composition
from app.shared.actor import Actor, Role

from fastapi import Depends, Request


async def get_teacher_profile(
    user_id: UUID,
    request: Request,
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    composition: Annotated[Composition, Depends(get_composition)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> JsonObject:
    """Return a teacher's account, week timetable and lessons without attendance."""
    return await composition.build_teacher_profile.execute(
        actor, user_id, ip=ip, user_agent=request.headers.get("user-agent")
    )

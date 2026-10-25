"""GET /v1/admin/students/{user_id}."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.dependencies import get_client_ip, require_roles
from app.interfaces.http.v1.composition.dependencies import get_composition
from app.interfaces.http.v1.composition.ports import JsonObject
from app.interfaces.http.v1.composition.services import Composition
from app.shared.actor import Actor, Role

from fastapi import Depends, Request


async def get_student_360(
    user_id: UUID,
    request: Request,
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    composition: Annotated[Composition, Depends(get_composition)],
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> JsonObject:
    """Return everything about one student; the view is audited."""
    return await composition.build_student_360.execute(
        actor, user_id, ip=ip, user_agent=request.headers.get("user-agent")
    )

"""GET /v1/me/group: the caller's group with its homeroom teacher and head student."""

from typing import Annotated, Any

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_marks.schemas import MyGroupResponse
from app.shared.actor import Actor, Role

from fastapi import Depends


async def get_my_group(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
) -> MyGroupResponse:
    """The group card and members; open to every student of the group."""
    data: dict[str, Any] = await container.academic.marks.get_my_group.execute(actor)
    return MyGroupResponse.model_validate(data)

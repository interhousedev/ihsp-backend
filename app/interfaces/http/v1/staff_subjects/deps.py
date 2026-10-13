"""Dependencies of the staff subject group routes."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends, Path

ContainerDep = Annotated[Container, Depends(get_container)]
StaffActor = Annotated[Actor, Depends(require_roles(Role.TEACHER, Role.ADMIN))]
SubgroupPath = Annotated[int, Path(ge=1, le=2)]

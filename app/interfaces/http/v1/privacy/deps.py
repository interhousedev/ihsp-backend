"""Dependencies of the privacy routes."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container, require_roles
from app.shared.actor import Actor, Role

from fastapi import Depends

ContainerDep = Annotated[Container, Depends(get_container)]
UserActor = Annotated[Actor, Depends(get_actor)]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]

"""Dependencies of the feedback routes."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.shared.actor import Actor

from fastapi import Depends

ContainerDep = Annotated[Container, Depends(get_container)]
UserActor = Annotated[Actor, Depends(get_actor)]

"""Dependencies shared by the authoring routes."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.modules.lms.wiring_authoring import AuthoringServices
from app.shared.actor import Actor

from fastapi import Depends

ActorDep = Annotated[Actor, Depends(get_actor)]


def get_authoring(
    container: Annotated[Container, Depends(get_container)],
) -> AuthoringServices:
    """Return the authoring use cases of the container (`container.lms.authoring`)."""
    services: AuthoringServices = container.lms.authoring
    return services


AuthoringDep = Annotated[AuthoringServices, Depends(get_authoring)]

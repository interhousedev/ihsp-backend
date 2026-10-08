"""Shared FastAPI dependencies of the identity routes."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container, require_roles
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.wiring_auth import AuthServices
from app.shared.actor import Actor, Role

from fastapi import Depends, Request


async def get_request_context(request: Request) -> RequestContext:
    """Client IP (set by uvicorn from trusted proxies) and user agent."""
    client = request.client
    return RequestContext(
        ip=client.host if client else None,
        user_agent=request.headers.get("user-agent"),
    )


def get_auth(container: Annotated[Container, Depends(get_container)]) -> AuthServices:
    """The identity auth services of the container."""
    services: AuthServices = container.identity.auth
    return services


require_admin = require_roles(Role.ADMIN)

ContainerDep = Annotated[Container, Depends(get_container)]
AuthDep = Annotated[AuthServices, Depends(get_auth)]
ActorDep = Annotated[Actor, Depends(get_actor)]
AdminDep = Annotated[Actor, Depends(require_admin)]
CtxDep = Annotated[RequestContext, Depends(get_request_context)]

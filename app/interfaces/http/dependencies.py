"""FastAPI dependencies: container, actor, roles, client IP."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from app.bootstrap.container import Container
from app.shared.actor import Actor, Role
from app.shared.base_error import UnauthorizedError
from app.shared.client_ip import IPNetwork, client_address
from app.shared.contracts.auth import AUDIENCE_API
from app.shared.usage_context import bind_usage_actor

from fastapi import Depends, Request


def get_container(request: Request) -> Container:
    """Return the container stored on the app by create_app."""
    container: Container = request.app.state.container
    return container


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthorizedError(support_details="malformed Authorization header")
    return token.strip()


async def _verify(container: Container, token: str) -> Actor:
    if container.identity is None:
        raise UnauthorizedError(support_details="identity module is not wired")
    actor: Actor = await container.identity.token_verifier.verify(
        token, audience=AUDIENCE_API
    )
    # The model calls this request makes are counted for this actor (usage ledger).
    bind_usage_actor(actor)
    return actor


async def get_actor(
    request: Request, container: Annotated[Container, Depends(get_container)]
) -> Actor:
    """Authenticate the Bearer token (audience ihsp-api) or raise 401."""
    token = _bearer_token(request)
    if token is None:
        raise UnauthorizedError(support_details="missing Authorization header")
    return await _verify(container, token)


async def get_optional_actor(
    request: Request, container: Annotated[Container, Depends(get_container)]
) -> Actor | None:
    """Return the actor, or None when no Authorization header is sent."""
    token = _bearer_token(request)
    if token is None:
        return None
    return await _verify(container, token)


def require_roles(*roles: Role) -> Callable[..., Awaitable[Actor]]:
    """Build a dependency that returns the actor if they hold one of the roles."""

    async def dependency(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
        actor.require(*roles)
        return actor

    return dependency


def _trusted_proxies(request: Request) -> tuple[IPNetwork, ...]:
    container = getattr(request.app.state, "container", None)
    if container is None:
        return ()
    networks: tuple[IPNetwork, ...] = container.settings.http.trusted_networks
    return networks


async def get_client_ip(request: Request) -> str | None:
    """Return the real client IP; X-Forwarded-For counts only from a trusted proxy.

    uvicorn runs without proxy_headers, so the TCP peer is never rewritten.
    """
    peer = request.client.host if request.client else None
    return client_address(
        peer, request.headers.get("x-forwarded-for"), _trusted_proxies(request)
    )

"""OAuth clients of remote MCP connectors: registration and a user's own clients."""

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.revoke_connector import RevokeConnector
from app.modules.identity.domain.errors import ConnectorInvalidError, RoleMissingError
from app.modules.identity.domain.mcp_clients import (
    DCR_AUTH_METHODS,
    EXACT_REDIRECTS,
    MAX_OWN_CLIENTS,
    SERVICE_NAMES,
    Service,
    is_safe_own_redirect,
    service_of_redirect,
)
from app.modules.identity.domain.scopes import (
    AUDIENCE_BY_SERVER,
    SERVERS,
    Server,
    role_may_use_server,
    scope_names,
)
from app.modules.identity.ports.hydra_gateway import (
    HydraClient,
    HydraGateway,
    NewHydraClient,
)
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import ConflictError, NotFoundError
from app.shared.rate_limit import RateLimiter
from app.shared.redis_util import RedisKeyLock

REGISTRATIONS_PER_HOUR = 120
"""Per address. ChatGPT, Claude and Gemini each register from shared addresses."""

PROVISION_LOCK_TTL_SECONDS = 30
"""Longer than one Hydra create call; a crashed holder frees the key by then."""
PROVISION_LOCK_WAIT_SECONDS = 0.1
PROVISION_LOCK_ATTEMPTS = 100
"""A second 'Yes' waits up to 10 s for the first one, then reads its client."""

PROVISIONED_SERVICES: frozenset[str] = frozenset({"chatgpt", "gemini", "claude"})
"""Services whose steps use a pre-created client (one fixed redirect URI)."""


@dataclass(frozen=True, slots=True)
class ProvisionedClient:
    """The client of a service; `client_secret` is set only when this call made it."""

    client: HydraClient
    client_secret: str | None
    created: bool


def client_scope() -> str:
    """Everything a client may ask for; the consent screen narrows it per server."""
    names: set[str] = set()
    for server in SERVERS:
        names |= scope_names(server)
    return " ".join(["openid", "offline", "offline_access", *sorted(names)])


def client_audience() -> list[str]:
    """Audiences a client may request with the `audience` parameter."""
    return [AUDIENCE_BY_SERVER[server] for server in SERVERS]


class RegistrationRefusedError(Exception):
    """RFC 7591 section 3.2.2: answered as `{error, error_description}` with 400."""

    def __init__(self, error: str, description: str) -> None:
        """Keep the two fields of the error response."""
        super().__init__(error)
        self.error = error
        self.description = description


@dataclass(frozen=True, slots=True)
class RegisterMcpClient:
    """POST /v1/oauth/mcp/register: self-registration, only for allowlisted URIs.

    Everything except the redirect URIs and the auth method is decided here: a client
    cannot pick its scopes, its grants, a `jwks_uri` for Hydra to fetch, or its name
    when the redirect URI already says who it is.
    """

    hydra: HydraGateway
    rate_limiter: RateLimiter
    extra_redirects: tuple[str, ...] = ()

    @property
    def scope(self) -> str:
        """The scope every registered client gets."""
        return client_scope()

    async def execute(
        self,
        *,
        redirect_uris: list[str],
        client_name: str | None,
        auth_method: str | None,
        ctx: RequestContext,
    ) -> NewHydraClient:
        """Create the client; raise RegistrationRefusedError for what is not allowed."""
        await self.rate_limiter.hit(
            f"mcp-register:{ctx.ip or 'unknown'}",
            limit=REGISTRATIONS_PER_HOUR,
            window_seconds=3600,
        )
        service = self._service(redirect_uris)
        # RFC 7591 section 2: an omitted method means client_secret_basic.
        method = auth_method or "client_secret_basic"
        if method not in DCR_AUTH_METHODS:
            raise RegistrationRefusedError(
                "invalid_client_metadata", "unsupported token_endpoint_auth_method"
            )
        name = SERVICE_NAMES[service]
        if service == "custom" and client_name and client_name.strip():
            name = client_name.strip()[:80]
        return await self.hydra.create_client(
            name=name,
            redirect_uris=redirect_uris,
            scope=client_scope(),
            audience=client_audience(),
            auth_method=method,
            metadata={"service": service, "dynamic": True},
        )

    def _service(self, redirect_uris: list[str]) -> Service:
        services = {
            service_of_redirect(uri, extra=self.extra_redirects)
            for uri in redirect_uris
        }
        if not redirect_uris or None in services or len(services) != 1:
            raise RegistrationRefusedError(
                "invalid_redirect_uri", "redirect_uris are not on the allowlist"
            )
        service = services.pop()
        assert service is not None  # refused above
        return service


@dataclass(frozen=True, slots=True)
class McpClients:
    """A user's own pre-registered clients, for clients that ask for an ID and secret.

    Only the owner can pass consent with such a client (`mcp_server` refuses anyone
    else), so a custom redirect URI cannot be used to phish another user.
    """

    uow_factory: UowFactory
    hydra: HydraGateway
    revoke_connector: RevokeConnector
    lock: RedisKeyLock
    extra_redirects: tuple[str, ...] = ()

    async def owned(self, actor: Actor) -> list[HydraClient]:
        """The caller's clients."""
        owner = str(actor.user_id)
        return [
            client
            for client in await self.hydra.list_clients()
            if client.metadata.get("owner_user_id") == owner
        ]

    async def create(
        self,
        actor: Actor,
        *,
        service: Service,
        server: Server,
        redirect_uri: str,
        name: str | None,
    ) -> NewHydraClient:
        """Create a confidential client; the secret is in this result only."""
        if not role_may_use_server(actor.roles, server):
            raise RoleMissingError(params={"server": server})
        if not self._allowed(service, redirect_uri):
            raise ConnectorInvalidError(params={"reason": "redirect-uri"})
        if len(await self.owned(actor)) >= MAX_OWN_CLIENTS:
            raise ConnectorInvalidError(params={"reason": "too-many-clients"})
        metadata: dict[str, Any] = {
            "service": service,
            "dynamic": True,
            "owner_user_id": str(actor.user_id),
            "mcp_server": server,
        }
        return await self.hydra.create_client(
            name=(name or "").strip()[:80] or SERVICE_NAMES[service],
            redirect_uris=[redirect_uri],
            scope=client_scope(),
            audience=[AUDIENCE_BY_SERVER[server]],
            auth_method="client_secret_post",
            metadata=metadata,
        )

    async def provision(
        self, actor: Actor, *, service: Service, server: Server
    ) -> ProvisionedClient:
        """Create the OAuth client of a service once; a repeat returns it, no secret."""
        if service not in PROVISIONED_SERVICES:
            raise ConnectorInvalidError(params={"reason": "service"})
        if not role_may_use_server(actor.roles, server):
            raise RoleMissingError(params={"server": server})
        # The check and the create must be one step per user and service: two
        # concurrent 'Yes' clicks would otherwise both see no client and both create.
        key = f"id:mcp-provision:{actor.user_id}:{service}:{server}"
        token = await self._take_provision_lock(key)
        try:
            return await self._provision_once(actor, service=service, server=server)
        finally:
            await asyncio.shield(self.lock.release(key, token))

    async def _take_provision_lock(self, key: str) -> str:
        for _ in range(PROVISION_LOCK_ATTEMPTS):
            token = await self.lock.acquire(key, PROVISION_LOCK_TTL_SECONDS)
            if token is not None:
                return token
            await asyncio.sleep(PROVISION_LOCK_WAIT_SECONDS)
        raise ConflictError(params={})

    async def _provision_once(
        self, actor: Actor, *, service: Service, server: Server
    ) -> ProvisionedClient:
        for client in await self.owned(actor):
            if (
                client.metadata.get("service") == service
                and client.metadata.get("mcp_server") == server
            ):
                return ProvisionedClient(
                    client=client, client_secret=None, created=False
                )
        created = await self.create(
            actor,
            service=service,
            server=server,
            redirect_uri=EXACT_REDIRECTS[service][0],
            name=None,
        )
        if created.client_secret is None:
            raise RuntimeError("client_secret_post client without a secret")
        return ProvisionedClient(
            client=created.client, client_secret=created.client_secret, created=True
        )

    def _allowed(self, service: Service, uri: str) -> bool:
        if service == "custom":
            return is_safe_own_redirect(uri)
        return service_of_redirect(uri) == service

    async def delete(self, actor: Actor, client_id: str, ctx: RequestContext) -> None:
        """Revoke the connectors of the client and delete it; 404 for someone else's."""
        client = await self.hydra.get_client(client_id)
        if client is None or client.metadata.get("owner_user_id") != str(actor.user_id):
            raise NotFoundError(params={"client_id": client_id})
        ids = await self._active_connectors(actor.user_id, client_id)
        for connector_id in ids:
            await self.revoke_connector.execute(actor, connector_id, ctx)
        await self.hydra.delete_client(client_id)

    async def _active_connectors(self, user_id: UUID, client_id: str) -> list[UUID]:
        async with self.uow_factory() as uow:
            connectors = await uow.connectors.list_for_user(user_id)
        return [
            c.id
            for c in connectors
            if c.hydra_client_id == client_id and c.revoked_at is None
        ]

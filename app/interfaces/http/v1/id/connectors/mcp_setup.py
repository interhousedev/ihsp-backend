"""Setup data per AI service and a user's own OAuth clients of MCP connectors."""

from typing import Literal

from app.interfaces.http.v1.id.connectors.schemas import Server
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep
from app.modules.identity.application.get_mcp_setup import (
    AuthMode,
    Availability,
    McpSetup,
    OAuthSettings,
)
from app.modules.identity.domain.mcp_clients import Service
from app.modules.identity.ports.hydra_gateway import HydraClient

from fastapi import Response
from pydantic import BaseModel, Field


class OAuthSettingsResponse(BaseModel):
    """OAuth settings of a client configured by hand. Contains no secret."""

    issuer: str
    discovery_url: str
    authorization_endpoint: str
    token_endpoint: str
    revocation_endpoint: str
    registration_endpoint: str
    jwks_uri: str
    protected_resource_metadata_url: str
    resource: str
    audience: str
    scopes: list[str]
    client_scopes: str
    code_challenge_method: str
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_methods: list[str]
    redirect_uris: list[str]
    redirect_uri_patterns: list[str]
    own_client_route: str

    @classmethod
    def of(cls, oauth: OAuthSettings) -> "OAuthSettingsResponse":
        """Map the settings."""
        return cls(
            issuer=oauth.issuer,
            discovery_url=oauth.discovery_url,
            authorization_endpoint=oauth.authorization_endpoint,
            token_endpoint=oauth.token_endpoint,
            revocation_endpoint=oauth.revocation_endpoint,
            registration_endpoint=oauth.registration_endpoint,
            jwks_uri=oauth.jwks_uri,
            protected_resource_metadata_url=oauth.protected_resource_metadata_url,
            resource=oauth.resource,
            audience=oauth.audience,
            scopes=oauth.scopes,
            client_scopes=oauth.client_scopes,
            code_challenge_method=oauth.code_challenge_method,
            grant_types=oauth.grant_types,
            response_types=oauth.response_types,
            token_endpoint_auth_methods=oauth.token_endpoint_auth_methods,
            redirect_uris=oauth.redirect_uris,
            redirect_uri_patterns=oauth.redirect_uri_patterns,
            own_client_route=oauth.own_client_route,
        )


class McpSetupResponse(BaseModel):
    """What the user enters. `notes` are machine codes the web app translates."""

    service: Service
    server: Server
    server_url: str
    availability: Availability
    auth_modes: list[AuthMode]
    notes: list[str]
    docs_url: str | None
    oauth: OAuthSettingsResponse | None
    token_route: str | None

    @classmethod
    def of(cls, setup: McpSetup) -> "McpSetupResponse":
        """Map the setup."""
        return cls(
            service=setup.service,
            server=setup.server,
            server_url=setup.server_url,
            availability=setup.facts.availability,
            auth_modes=list(setup.facts.auth_modes),
            notes=list(setup.facts.notes),
            docs_url=setup.facts.docs_url,
            oauth=OAuthSettingsResponse.of(setup.oauth) if setup.oauth else None,
            token_route=setup.token_route,
        )


class McpClientResponse(BaseModel):
    """A user's own OAuth client (never the secret)."""

    client_id: str
    name: str
    service: str | None
    server: Server | None
    redirect_uris: list[str]

    @classmethod
    def of(cls, client: HydraClient) -> "McpClientResponse":
        """Map a Hydra client."""
        return cls(
            client_id=client.client_id,
            name=client.client_name,
            service=client.metadata.get("service"),
            server=client.metadata.get("mcp_server"),
            redirect_uris=list(client.redirect_uris),
        )


class CreateMcpClientBody(BaseModel):
    """POST /v1/id/me/mcp-clients."""

    service: Service
    server: Server
    redirect_uri: str = Field(min_length=1, max_length=512)
    name: str | None = Field(default=None, max_length=80)


class NewMcpClientResponse(BaseModel):
    """The client and its secret, shown once."""

    client: McpClientResponse
    client_secret: str
    token_endpoint_auth_method: Literal["client_secret_post"] = "client_secret_post"


class ProvisionedMcpSetupResponse(BaseModel):
    """A pre-created client; `client_secret` is set only when this call created it."""

    client: McpClientResponse
    client_secret: str | None
    created: bool


async def get_mcp_setup(
    service: Service, actor: ActorDep, auth: AuthDep, server: Server = "student"
) -> McpSetupResponse:
    """What to enter to connect `server` to one AI service."""
    return McpSetupResponse.of(auth.get_mcp_setup.execute(actor, service, server))


async def provision_mcp_setup(
    service: Service, actor: ActorDep, auth: AuthDep, server: Server = "student"
) -> ProvisionedMcpSetupResponse:
    """Pre-create the OAuth client of `service` (MCP-5); a repeat has no secret."""
    result = await auth.mcp_clients.provision(actor, service=service, server=server)
    return ProvisionedMcpSetupResponse(
        client=McpClientResponse.of(result.client),
        client_secret=result.client_secret,
        created=result.created,
    )


async def get_mcp_clients(actor: ActorDep, auth: AuthDep) -> list[McpClientResponse]:
    """The caller's own OAuth clients."""
    clients = await auth.mcp_clients.owned(actor)
    return [McpClientResponse.of(client) for client in clients]


async def post_mcp_client(
    body: CreateMcpClientBody, actor: ActorDep, auth: AuthDep
) -> NewMcpClientResponse:
    """Create a client for one exact redirect URI; the secret is shown only here."""
    created = await auth.mcp_clients.create(
        actor,
        service=body.service,
        server=body.server,
        redirect_uri=body.redirect_uri,
        name=body.name,
    )
    assert created.client_secret is not None  # client_secret_post always has one
    return NewMcpClientResponse(
        client=McpClientResponse.of(created.client),
        client_secret=created.client_secret,
    )


async def delete_mcp_client(
    client_id: str, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Revoke the connectors of the client and delete it."""
    await auth.mcp_clients.delete(actor, client_id, ctx)
    return Response(status_code=204)

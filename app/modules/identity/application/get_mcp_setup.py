"""GET /v1/id/me/mcp-setup/{service}: what a user enters to connect one AI service."""

from dataclasses import dataclass
from typing import Final, Literal

from app.modules.identity.application.mcp_clients import client_scope
from app.modules.identity.domain.errors import RoleMissingError
from app.modules.identity.domain.mcp_clients import (
    DCR_AUTH_METHODS,
    EXACT_REDIRECTS,
    REDIRECT_TEMPLATES,
    Service,
)
from app.modules.identity.domain.scopes import (
    AUDIENCE_BY_SERVER,
    Server,
    role_may_use_server,
    scope_names,
)
from app.shared.actor import Actor

AuthMode = Literal["oauth_dcr", "oauth_client", "static_token"]
Availability = Literal["available", "limited", "plan_gated"]

OWN_CLIENTS_ROUTE: Final = "/v1/id/me/mcp-clients"
TOKEN_ROUTE: Final = "/v1/id/me/connectors"


@dataclass(frozen=True, slots=True)
class ServiceFacts:
    """What the vendor's documentation says about one service (machine codes only)."""

    availability: Availability
    auth_modes: tuple[AuthMode, ...]
    notes: tuple[str, ...]
    docs_url: str | None


FACTS: Final[dict[Service, ServiceFacts]] = {
    "chatgpt": ServiceFacts(
        availability="plan_gated",
        auth_modes=("oauth_dcr", "oauth_client"),
        notes=("business_enterprise_edu_full_mcp", "pro_read_fetch_only"),
        docs_url=(
            "https://help.openai.com/en/articles/"
            "12584461-developer-mode-and-mcp-apps-in-chatgpt"
        ),
    ),
    "gemini": ServiceFacts(
        availability="limited",
        auth_modes=("oauth_dcr", "oauth_client"),
        notes=(
            "gemini_app_us_18_personal_account_keep_activity_on",
            "gemini_enterprise_admin_sets_up_client_and_pkce",
            "gemini_web_generated_redirect",
            "gemini_cli_redirect",
        ),
        docs_url="https://support.google.com/gemini/answer/17209137",
    ),
    "claude": ServiceFacts(
        availability="limited",
        auth_modes=("oauth_dcr", "oauth_client", "static_token"),
        notes=(
            "free_plan_one_custom_connector",
            "team_enterprise_owner_adds_connector",
            "static_headers_beta_owner_only",
        ),
        docs_url="https://claude.com/docs/connectors/custom/remote-mcp",
    ),
    "custom": ServiceFacts(
        availability="available",
        auth_modes=("oauth_dcr", "oauth_client", "static_token"),
        notes=("dcr_needs_allowlisted_redirect_uri",),
        docs_url=None,
    ),
}


@dataclass(frozen=True, slots=True)
class McpEndpoints:
    """Public URLs of the deployment."""

    issuer: str
    api_url: str
    mcp_base: str


@dataclass(frozen=True, slots=True)
class OAuthSettings:
    """Everything a client configured by hand needs."""

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


@dataclass(frozen=True, slots=True)
class McpSetup:
    """The answer of the route."""

    service: Service
    server: Server
    server_url: str
    facts: ServiceFacts
    oauth: OAuthSettings | None
    token_route: str | None


@dataclass(frozen=True, slots=True)
class GetMcpSetup:
    """Builds the setup data; contains no secret and creates nothing."""

    endpoints: McpEndpoints

    def execute(self, actor: Actor, service: Service, server: Server) -> McpSetup:
        """Setup of `server` for `service`; refuses a role that may not use it."""
        if not role_may_use_server(actor.roles, server):
            raise RoleMissingError(params={"server": server})
        facts = FACTS[service]
        return McpSetup(
            service=service,
            server=server,
            server_url=self._server_url(server),
            facts=facts,
            oauth=self._oauth(service, server),
            token_route=TOKEN_ROUTE if "static_token" in facts.auth_modes else None,
        )

    def _server_url(self, server: Server) -> str:
        return f"{self.endpoints.mcp_base.rstrip('/')}/{server}"

    def _oauth(self, service: Service, server: Server) -> OAuthSettings:
        base = self.endpoints.issuer.rstrip("/")
        url = self._server_url(server)
        origin, _, path = url.partition("://")[2].partition("/")
        scheme = url.partition("://")[0]
        return OAuthSettings(
            issuer=self.endpoints.issuer,
            discovery_url=f"{base}/.well-known/oauth-authorization-server",
            authorization_endpoint=f"{base}/oauth2/auth",
            token_endpoint=f"{base}/oauth2/token",
            revocation_endpoint=f"{base}/oauth2/revoke",
            registration_endpoint=(
                f"{self.endpoints.api_url.rstrip('/')}/v1/oauth/mcp/register"
            ),
            jwks_uri=f"{base}/.well-known/jwks.json",
            protected_resource_metadata_url=(
                f"{scheme}://{origin}/.well-known/oauth-protected-resource/{path}"
            ),
            resource=url,
            audience=AUDIENCE_BY_SERVER[server],
            scopes=sorted(scope_names(server)),
            client_scopes=client_scope(),
            code_challenge_method="S256",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_methods=sorted(DCR_AUTH_METHODS),
            redirect_uris=list(EXACT_REDIRECTS.get(service, ())),
            redirect_uri_patterns=list(REDIRECT_TEMPLATES.get(service, ())),
            own_client_route=OWN_CLIENTS_ROUTE,
        )

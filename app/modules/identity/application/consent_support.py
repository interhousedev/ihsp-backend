"""Pure helpers shared by the consent use cases."""

from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from app.modules.identity.domain.errors import ConnectorInvalidError
from app.modules.identity.domain.scopes import (
    SCOPE_CATALOG,
    SERVERS,
    Server,
    scope_names,
    server_from_audience,
    server_from_resource,
)
from app.modules.identity.domain.user import User
from app.modules.identity.ports.hydra_gateway import ConsentRequest, HydraClient


def mcp_server(request: ConsentRequest, mcp_base: str) -> Server:
    """Which MCP server a client asks for, after the checks of the binding.

    A `resource` parameter must be this deployment's exact URL of a server; without one
    the requested audience decides, then the server a user's own client was made for.
    A user's own client is usable by that user only, and PKCE must be S256.
    """
    query = parse_qs(urlparse(request.request_url).query)
    _require_s256(query)
    client = request.client
    owner = client.metadata.get("owner_user_id")
    if owner is not None and owner != request.subject:
        raise ConnectorInvalidError(params={"reason": "client-owner"})
    server = _named_server(request, query.get("resource", []), mcp_base)
    bound = client.metadata.get("mcp_server")
    if bound is not None and server is not None and bound != server:
        raise ConnectorInvalidError(params={"reason": "client-server"})
    server = server or (bound if bound in SERVERS else None)
    if server is None:
        raise ConnectorInvalidError(params={"reason": "unknown-server"})
    return server


def _require_s256(query: dict[str, list[str]]) -> None:
    """Hydra also accepts `plain`, which OAuth 2.1 clients must not use."""
    if not query.get("code_challenge"):
        return  # Hydra enforces PKCE itself and refuses a request without it
    if query.get("code_challenge_method") != ["S256"]:
        raise ConnectorInvalidError(params={"reason": "pkce"})


def _named_server(
    request: ConsentRequest, resources: list[str], mcp_base: str
) -> Server | None:
    if resources:
        servers = {server_from_resource(value, mcp_base) for value in resources}
        if None in servers or len(servers) != 1:
            raise ConnectorInvalidError(params={"reason": "resource"})
        return servers.pop()
    for audience in request.requested_audience:
        server = server_from_audience(audience)
        if server is not None:
            return server
    return None


def redirect_domain(request: ConsentRequest) -> str:
    """Host the client will be sent back to (shown on the consent screen)."""
    query = parse_qs(urlparse(request.request_url).query)
    uri = (query.get("redirect_uri") or [""])[0]
    if not uri and request.client.redirect_uris:
        uri = request.client.redirect_uris[0]
    return urlparse(uri).hostname or ""


def is_verified(client: HydraClient) -> bool:
    """Administration marked the client as verified."""
    return bool(client.metadata.get("verified"))


def is_dynamic(client: HydraClient) -> bool:
    """Registered by the client itself (DCR cannot set metadata, so default True)."""
    return bool(client.metadata.get("dynamic", True))


def requested_scopes(request: ConsentRequest, server: Server) -> list[str]:
    """Scopes of the server the client asked for; all of them if it asked for none."""
    asked = set(request.requested_scope)
    ordered = [info.scope for info in SCOPE_CATALOG[server]]
    chosen = [scope for scope in ordered if scope in asked]
    return chosen or ordered


def grantable(server: Server, requested: list[str], granted: list[str]) -> list[str]:
    """The granted scopes, if they are a non-empty subset of what may be asked."""
    allowed = scope_names(server) & set(requested)
    unique = list(dict.fromkeys(granted))
    if not unique or not set(unique) <= allowed:
        raise ConnectorInvalidError(params={"reason": "scopes"})
    return unique


def access_claims(
    user: User,
    *,
    sid: str,
    amr: list[str],
    mfa_at: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The claim set put into every access token (see the token hook)."""
    claims: dict[str, Any] = {
        "auth_epoch": user.auth_epoch,
        "roles": sorted(role.value for role in user.roles),
        "amr": amr,
        "mfa_at": mfa_at,
        "sid": sid,
    }
    claims.update(extra or {})
    return claims


def parse_uuid(value: object) -> UUID | None:
    """UUID or None for anything else."""
    try:
        return UUID(str(value))
    except ValueError:
        return None


def parse_datetime(value: object) -> datetime | None:
    """ISO datetime or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

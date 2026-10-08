"""Pure helpers shared by the consent use cases."""

from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from app.modules.identity.domain.errors import ConnectorInvalidError
from app.modules.identity.domain.scopes import (
    SCOPE_CATALOG,
    Server,
    scope_names,
    server_from_resource,
)
from app.modules.identity.domain.user import User
from app.modules.identity.ports.hydra_gateway import ConsentRequest, HydraClient


def mcp_server(request: ConsentRequest) -> Server:
    """Which MCP server a client asks for: `resource` parameter or audience."""
    query = parse_qs(urlparse(request.request_url).query)
    candidates = [*query.get("resource", []), *request.requested_audience]
    for candidate in candidates:
        server = server_from_resource(candidate)
        if server is not None:
            return server
    raise ConnectorInvalidError(params={"reason": "unknown-server"})


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

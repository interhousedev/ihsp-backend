"""URLs and transport security of the MCP servers."""

from urllib.parse import urlparse

from app.interfaces.mcp.constants import ServerName
from app.settings import Settings

from mcp.server.transport_security import TransportSecuritySettings

_DEV_HOSTS = ("localhost:*", "127.0.0.1:*", "[::1]:*")
_DEV_ORIGINS = ("http://localhost:*", "http://127.0.0.1:*", "http://[::1]:*")


def resource_url(settings: Settings, server: ServerName) -> str:
    """Return the public URL of one MCP server (URLS__MCP + /<server>)."""
    return f"{settings.urls.mcp.rstrip('/')}/{server}"


def transport_security(settings: Settings) -> TransportSecuritySettings:
    """Allow the host of URLS__MCP (and localhost outside production).

    The SDK rejects every other Host with 421 and every other Origin with 403
    (DNS-rebinding protection).
    """
    parsed = urlparse(settings.urls.mcp)
    host = parsed.hostname or "localhost"
    hosts = {host, f"{host}:*"}
    origins = {f"{parsed.scheme}://{parsed.netloc}"}
    if settings.env != "prod":
        hosts.update(_DEV_HOSTS)
        origins.update(_DEV_ORIGINS)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(hosts),
        allowed_origins=sorted(origins),
    )

"""OAuth clients of remote MCP connectors: which redirect URIs may be registered.

Hydra compares a redirect URI byte for byte with what the client registered, so this
table decides what can ever receive an authorization code. Most entries are one exact
URI. ChatGPT and Google put one generated path segment into theirs, so those entries
fix the scheme, the host and the path and leave only that segment open.

Sources (checked 2026-11-04):
- https://developers.openai.com/apps-sdk/build/auth
- https://developers.google.com/connected-apps/mcp/oauth
- https://docs.cloud.google.com/gemini/enterprise/docs/connectors/custom-mcp-server/
  set-up-custom-mcp-server
- https://claude.com/docs/connectors/building/authentication
"""

import re
from collections.abc import Iterable
from typing import Final, Literal, get_args
from urllib.parse import urlparse

Service = Literal["chatgpt", "gemini", "claude", "custom"]
SERVICES: Final[tuple[Service, ...]] = get_args(Service)

SERVICE_NAMES: Final[dict[Service, str]] = {
    "chatgpt": "ChatGPT",
    "gemini": "Google Gemini",
    "claude": "Claude",
    "custom": "MCP client",
}
"""Client names on the consent screen; a client cannot choose to look like another."""

EXACT_REDIRECTS: Final[dict[Service, tuple[str, ...]]] = {
    "chatgpt": ("https://chatgpt.com/connector_platform_oauth_redirect",),
    "gemini": ("https://vertexaisearch.cloud.google.com/oauth-redirect",),
    "claude": ("https://claude.ai/api/mcp/auth_callback",),
}

_SEGMENT = "[A-Za-z0-9_-]{1,128}"
_GOOGLE_HOSTS = "oauth-redirect(?:-sandbox|-test)?\\.googleusercontent\\.com"

REDIRECT_TEMPLATES: Final[dict[Service, tuple[str, ...]]] = {
    "chatgpt": (f"https://chatgpt\\.com/connector/oauth/{_SEGMENT}",),
    "gemini": (f"https://{_GOOGLE_HOSTS}/[ra]/{_SEGMENT}",),
}
"""Full-match patterns of the generated URIs; shown as they are in the setup data."""

DCR_AUTH_METHODS: Final = frozenset(
    {"none", "client_secret_basic", "client_secret_post"}
)
MAX_OWN_CLIENTS: Final = 5
REDIRECT_MAX_LENGTH: Final = 512
_LOOPBACK_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})


def service_of_redirect(uri: str, *, extra: Iterable[str] = ()) -> Service | None:
    """The service a redirect URI belongs to; `custom` for an operator's exact URI."""
    for service, uris in EXACT_REDIRECTS.items():
        if uri in uris:
            return service
    for service, patterns in REDIRECT_TEMPLATES.items():
        if any(re.fullmatch(pattern, uri) for pattern in patterns):
            return service
    return "custom" if uri in set(extra) else None


def is_safe_own_redirect(uri: str) -> bool:
    """A URI a user may register for their own client: https, or http on loopback."""
    if len(uri) > REDIRECT_MAX_LENGTH or "*" in uri or any(c.isspace() for c in uri):
        return False
    try:
        parsed = urlparse(uri)
        host = parsed.hostname
    except ValueError:
        return False
    if not host or parsed.username or parsed.password or parsed.fragment:
        return False
    return parsed.scheme == "https" or (
        parsed.scheme == "http" and host in _LOOPBACK_HOSTS
    )

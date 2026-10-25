"""MCP connector entity and token format."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from app.shared.ids import hash_token, random_token

TOKEN_PREFIX = "ihsp_mcp_"
PREFIX_LENGTH = 8
ALLOWED_EXPIRY_DAYS = (30, 90, 365)
ADMIN_MAX_EXPIRY_DAYS = 30
OAUTH_EXPIRY_DAYS = 365


@dataclass(slots=True)
class McpConnector:
    """An AI client connected to an MCP server on behalf of a user."""

    id: UUID
    user_id: UUID
    name: str
    server: str
    scopes: list[str]
    course_ids: list[UUID] | None = None
    token_hash: str | None = None
    token_prefix: str | None = None
    hydra_client_id: str | None = None
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = field(default=None)

    @property
    def kind(self) -> Literal["token", "oauth"]:
        """Token connectors hold a hash; OAuth connectors live in Hydra."""
        return "token" if self.token_hash is not None else "oauth"

    def is_active(self, now: datetime) -> bool:
        """True while not revoked and not expired."""
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > now


def new_token() -> tuple[str, str, str]:
    """Return (token, sha256 hash, display prefix) for a fresh connector token."""
    secret = random_token(32)
    token = TOKEN_PREFIX + secret
    return token, hash_token(token), secret[:PREFIX_LENGTH]


def looks_like_token(value: str) -> bool:
    """Cheap format check before hitting the database."""
    return value.startswith(TOKEN_PREFIX) and len(value) > len(TOKEN_PREFIX)

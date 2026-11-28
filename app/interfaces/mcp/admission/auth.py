"""Bearer tokens of `/mcp/admission`: personal tokens on top of the usual verifier.

The server is built like every other one (Hydra tokens with audience
`mcp-admission` and connector tokens go through `IhspTokenVerifier`). This wrapper
also accepts `ihsp_pat_` personal tokens of students: their old scopes
(`admission:read`, ...) become the server scopes they stand for (`pat_scopes`). A
token with a catalog scope, a non-student owner or no admission scope is refused.
The universal `/mcp/app` server keeps the plain verifier, so personal tokens never
open it.
"""

from dataclasses import replace
from typing import Protocol

from app.interfaces.mcp.auth import IhspAccessToken
from app.modules.identity.domain.personal_token import CATALOG_SCOPES, looks_like_token
from app.shared.actor import Actor, Role
from app.shared.base_error import BaseError
from app.shared.mcp_scopes import pat_scopes

import structlog
from mcp.server.auth.provider import AccessToken, TokenVerifier

log = structlog.get_logger(__name__)


class PersonalVerifier(Protocol):
    """Verifies `ihsp_pat_` personal tokens (identity module)."""

    async def verify_personal(self, token: str) -> Actor:
        """Return the token owner's actor or raise UnauthorizedError."""
        ...


class PersonalTokenVerifier:
    """SDK `TokenVerifier`: personal tokens here, every other token to `inner`."""

    def __init__(
        self, *, inner: TokenVerifier, personal: PersonalVerifier, resource_url: str
    ) -> None:
        """Keep the server's own verifier, the personal one and the public URL."""
        self._inner = inner
        self._personal = personal
        self.resource_url = resource_url

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the access token for a valid bearer token, else None (401)."""
        if not looks_like_token(token):
            return await self._inner.verify_token(token)
        try:
            actor = await self._personal.verify_personal(token)
        except BaseError as error:
            log.info("mcp.token_rejected", server="admission", code=error.code)
            return None
        reason = _refusal(actor)
        if reason is not None:
            log.info("mcp.token_rejected", server="admission", code=reason)
            return None
        actor = replace(actor, scopes=pat_scopes(actor.scopes))
        return IhspAccessToken(
            token="",  # the raw secret is never kept after verification
            client_id=actor.client_id or "personal-token",
            scopes=sorted(actor.scopes),
            resource=self.resource_url,
            subject=str(actor.user_id),
            claims={"server": "admission"},
            actor=actor,
        )


def _refusal(actor: Actor) -> str | None:
    if actor.scopes & CATALOG_SCOPES:
        return "scope-catalog"
    if not actor.has(Role.STUDENT):
        return "role-missing"
    if not pat_scopes(actor.scopes):
        return "scope-missing"
    return None

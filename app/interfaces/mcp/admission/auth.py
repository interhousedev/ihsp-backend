"""Bearer tokens of the admission MCP server (personal tokens and Hydra tokens)."""

from typing import Protocol

from app.interfaces.mcp.auth import IhspAccessToken
from app.modules.identity.domain.personal_token import (
    ADMISSION_SCOPES,
    CATALOG_SCOPES,
    looks_like_token,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import BaseError
from app.shared.contracts.auth import AUDIENCE_MCP_ADMISSION, AccessTokenVerifier

import structlog
from mcp.server.auth.provider import AccessToken

log = structlog.get_logger(__name__)


class PersonalVerifier(Protocol):
    """Verifies `ihsp_pat_` personal tokens (identity module)."""

    async def verify_personal(self, token: str) -> Actor:
        """Return the token owner's actor or raise UnauthorizedError."""
        ...


class AdmissionTokenVerifier:
    """SDK `TokenVerifier` for `/mcp/admission`.

    `ihsp_pat_` tokens are personal tokens (revocable, expiring); anything else
    is a Hydra token whose audience must be `mcp-admission`. Only students with
    at least one admission scope get through; None makes the SDK answer 401.
    """

    def __init__(
        self,
        *,
        access: AccessTokenVerifier,
        personal: PersonalVerifier,
        resource_url: str,
    ) -> None:
        """Keep both verifiers and the public URL of the server."""
        self._access = access
        self._personal = personal
        self.resource_url = resource_url

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the access token for a valid bearer token, else None."""
        try:
            actor = await self._authenticate(token)
        except BaseError as error:
            log.info("mcp.token_rejected", server="admission", code=error.code)
            return None
        if actor.scopes & CATALOG_SCOPES:
            log.info("mcp.token_rejected", server="admission", code="scope-catalog")
            return None
        if not actor.has(Role.STUDENT):
            log.info("mcp.token_rejected", server="admission", code="role-missing")
            return None
        if not actor.scopes & ADMISSION_SCOPES:
            log.info("mcp.token_rejected", server="admission", code="scope-missing")
            return None
        return IhspAccessToken(
            token="",  # the raw secret is never kept after verification
            client_id=actor.client_id or "personal-token",
            scopes=sorted(actor.scopes),
            resource=self.resource_url,
            subject=str(actor.user_id),
            claims={"server": "admission"},
            actor=actor,
        )

    async def _authenticate(self, token: str) -> Actor:
        if looks_like_token(token):
            return await self._personal.verify_personal(token)
        return await self._access.verify(token, audience=AUDIENCE_MCP_ADMISSION)

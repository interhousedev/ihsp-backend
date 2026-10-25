"""Our own RS256 assertions for Hydra's JWT-bearer grant (RFC 7523)."""

from datetime import timedelta
from functools import cache
from typing import Any
from uuid import UUID

from app.modules.identity.ports.assertion_signer import AssertionClaims
from app.shared.clock import Clock
from app.shared.ids import new_id

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import RSAKey

ASSERTION_TTL = timedelta(minutes=5)


@cache
def _load_keys(private_key_pem: str, key_id: str) -> tuple[RSAKey, RSAKey]:
    """Import the PEM once per process (RSA validation is slow)."""
    private = RSAKey.import_key(private_key_pem, parameters={"kid": key_id})
    public = RSAKey.import_key(
        private.as_dict(private=False), parameters={"kid": key_id}
    )
    return private, public


class JoseAssertionSigner:
    """Signs assertions with the identity key and reads them back in the token hook."""

    def __init__(
        self,
        *,
        private_key_pem: str,
        key_id: str,
        issuer: str,
        token_url: str,
        clock: Clock,
    ) -> None:
        """Load the private key; the public half verifies assertions in the hook."""
        self._key, self._public = _load_keys(private_key_pem, key_id)
        self._issuer = issuer
        self._token_url = token_url
        self._clock = clock

    def public_jwk(self) -> dict[str, Any]:
        """The public key to register as a trusted issuer in Hydra."""
        return dict(self._key.as_dict(private=False, use="sig", alg="RS256"))

    def sign(self, user_id: UUID, session_id: UUID, amr: list[str]) -> str:
        """Return a signed assertion valid for five minutes."""
        now = self._clock.now()
        claims = {
            "iss": self._issuer,
            "sub": str(user_id),
            "aud": self._token_url,
            "iat": int(now.timestamp()),
            "exp": int((now + ASSERTION_TTL).timestamp()),
            "jti": str(new_id()),
            "sid": str(session_id),
            "amr": amr,
        }
        header = {"alg": "RS256", "kid": self._key.kid}
        return jwt.encode(header, claims, self._key)

    def read(self, assertion: str) -> AssertionClaims | None:
        """Verify our signature and issuer; Hydra already checked expiry."""
        try:
            token = jwt.decode(assertion, self._public, algorithms=["RS256"])
            claims = token.claims
            if claims.get("iss") != self._issuer:
                return None
            return AssertionClaims(
                user_id=UUID(str(claims["sub"])),
                session_id=UUID(str(claims["sid"])),
                amr=tuple(str(item) for item in claims.get("amr", [])),
            )
        except (JoseError, KeyError, ValueError):
            return None

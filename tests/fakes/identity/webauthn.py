"""In-memory WebAuthn relying party: verification is scripted by the test."""

import base64
from typing import Any

from app.modules.identity.domain.errors import PasskeyInvalidError
from app.modules.identity.ports.webauthn import (
    CeremonyOptions,
    RegisteredCredential,
    VerifiedAssertion,
)


def b64url(raw: bytes) -> str:
    """Base64url without padding, as browsers send it."""
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _raw(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class FakeWebAuthn:
    """A credential passes when it echoes the last challenge in ``challenge``."""

    def __init__(self) -> None:
        """No ceremony yet."""
        self.counter = 0
        self.last_challenge = b""
        self.excluded: list[bytes] = []

    def _ceremony(self, kind: str) -> CeremonyOptions:
        self.counter += 1
        self.last_challenge = f"{kind}-{self.counter}".encode()
        return CeremonyOptions(
            options={"challenge": b64url(self.last_challenge), "rpId": "localhost"},
            challenge=self.last_challenge,
        )

    def registration_options(
        self,
        *,
        user_id: bytes,
        user_name: str,
        display_name: str,
        exclude: list[bytes],
    ) -> CeremonyOptions:
        """Remember what would be excluded."""
        self.excluded = list(exclude)
        return self._ceremony("reg")

    @staticmethod
    def _check(credential: dict[str, Any], challenge: bytes) -> None:
        if credential.get("challenge") != b64url(challenge):
            raise PasskeyInvalidError(params={"reason": "challenge"})

    def verify_registration(
        self, credential: dict[str, Any], challenge: bytes
    ) -> RegisteredCredential:
        """The credential id is ``rawId``; the public key is derived from it."""
        self._check(credential, challenge)
        raw = _raw(str(credential["rawId"]))
        return RegisteredCredential(
            credential_id=raw,
            public_key=b"pk-" + raw,
            sign_count=0,
            transports=["internal"],
        )

    def authentication_options(self) -> CeremonyOptions:
        """A new challenge."""
        return self._ceremony("auth")

    def verify_authentication(
        self,
        credential: dict[str, Any],
        challenge: bytes,
        *,
        public_key: bytes,
        sign_count: int,
    ) -> VerifiedAssertion:
        """The signature is fine when the public key matches the credential id."""
        self._check(credential, challenge)
        if public_key != b"pk-" + _raw(str(credential["rawId"])):
            raise PasskeyInvalidError(params={"reason": "signature"})
        return VerifiedAssertion(new_sign_count=sign_count + 1)


def credential(fake: FakeWebAuthn, raw_id: bytes, **extra: Any) -> dict[str, Any]:
    """A browser answer to the last ceremony of ``fake``."""
    return {
        "id": b64url(raw_id),
        "rawId": b64url(raw_id),
        "type": "public-key",
        "challenge": b64url(fake.last_challenge),
        "response": {},
        **extra,
    }

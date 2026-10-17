"""Port: WebAuthn ceremonies (options and verification) for passkeys."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class CeremonyOptions:
    """Options for navigator.credentials (JSON) and the challenge to remember."""

    options: dict[str, Any]
    challenge: bytes


@dataclass(frozen=True, slots=True)
class RegisteredCredential:
    """A verified new credential."""

    credential_id: bytes
    public_key: bytes
    sign_count: int
    transports: list[str] = field(default_factory=list)
    backed_up: bool = False


@dataclass(frozen=True, slots=True)
class VerifiedAssertion:
    """A verified sign-in with a stored credential."""

    new_sign_count: int
    backed_up: bool = False


class WebAuthn(Protocol):
    """Relying party of IHT ID; a failed verification raises PasskeyInvalidError."""

    def registration_options(
        self,
        *,
        user_id: bytes,
        user_name: str,
        display_name: str,
        exclude: list[bytes],
    ) -> CeremonyOptions:
        """Options for navigator.credentials.create (a discoverable credential)."""
        ...

    def verify_registration(
        self, credential: dict[str, Any], challenge: bytes
    ) -> RegisteredCredential:
        """Check the attestation response."""
        ...

    def authentication_options(self) -> CeremonyOptions:
        """Options for navigator.credentials.get (any passkey of this site)."""
        ...

    def verify_authentication(
        self,
        credential: dict[str, Any],
        challenge: bytes,
        *,
        public_key: bytes,
        sign_count: int,
    ) -> VerifiedAssertion:
        """Check the assertion signature, origin, RP id and user verification."""
        ...
